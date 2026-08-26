"""Restart-safe runner for the frozen empirical ten-task campaign."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import direct_additional_validate, direct_launch, direct_validate
from .direct_additional_constants import (
    ARTIFACT_DIR,
    BENCHMARK_ID,
    DATASET_DIGEST,
    DATASET_NAME,
    DOPPLER_LAUNCH_ID,
    EXCLUSION_PATH,
    EXPECTED_CELLS,
    HARBOR_VERSION,
    JOBS_DIR,
    MODEL,
    PER_CELL_CAP_USD,
    PREFLIGHT_DIR,
    PREFLIGHT_JOBS_DIR,
    PREPARATION_HASHES_PATH,
    RUNNER_SPEC_PATH,
    RUNS_DIR,
    SELECTION_PATH,
    SETTINGS_PATH,
    TASKS,
    THINHARNESS_COMMIT,
    TOTAL_CAP_USD,
)
from .direct_budget import DirectBudgetLedger
from .durable import append_jsonl, atomic_json
from .source_bundle import ExactCommitBundle, exact_commit_bundle

_LOCK = RUNS_DIR / "launch.lock"
_IDENTITY_FILES = (
    "configs/container-runtime-requirements.txt",
    "configs/direct-openai-20task-settings.json",
    "configs/direct-openai-additional-10-SHA256SUMS.json",
    "configs/direct-openai-additional-10-exclusion-proof.json",
    "configs/direct-openai-additional-10-runner-spec.json",
    "configs/direct-openai-additional-10-selection.json",
    "configs/native-tool-schemas.json",
    "configs/pi-native-tool-schemas.json",
    "configs/pi-subscription-package-lock.json",
    "configs/pi-subscription-package.json",
    "prompts/pi-0.84.2-system-prompt.md",
    "scripts/direct-openai-additional-10-full-checks.sh",
    "scripts/direct-openai-additional-10-preflight.sh",
    "scripts/install-direct-pi.sh",
    "scripts/install-direct-thinharness.sh",
    "scripts/run-direct-openai-additional-10.sh",
    "tbench/container_security.py",
    "tbench/direct_additional_constants.py",
    "tbench/direct_additional_launch.py",
    "tbench/direct_additional_validate.py",
    "tbench/direct_agent.py",
    "tbench/direct_budget.py",
    "tbench/direct_container.py",
    "tbench/direct_gateway.py",
    "tbench/direct_launch.py",
    "tbench/direct_validate.py",
    "tbench/durable.py",
    "tbench/pi_subscription_probe.mjs",
    "tbench/source_bundle.py",
    "uv.lock",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_frozen_inputs(root: Path) -> None:
    preparation = json.loads(PREPARATION_HASHES_PATH.read_text(encoding="utf-8"))
    for relative, expected in preparation["files"].items():
        path = direct_launch.REPOSITORY_ROOT / relative
        if not path.is_file() or _sha256(path) != expected:
            raise RuntimeError(f"frozen preparation hash differs: {relative}")
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    spec = json.loads(RUNNER_SPEC_PATH.read_text(encoding="utf-8"))
    proof = json.loads(EXCLUSION_PATH.read_text(encoding="utf-8"))
    if selection.get("benchmark_id") != BENCHMARK_ID or selection.get("planned_execution_order") != list(EXPECTED_CELLS):
        raise RuntimeError("frozen selection or Pi-then-ThinHarness order differs")
    if spec.get("planned_execution_order") != list(EXPECTED_CELLS) or spec.get("planned_cells") != 20:
        raise RuntimeError("frozen runner specification differs")
    if proof.get("selected_tasks") != list(TASKS) or proof.get("selected_conflicts") != []:
        raise RuntimeError("frozen exclusion proof differs")
    conflicts: list[Path] = []
    for launch_path in (direct_launch.REPOSITORY_ROOT / "artifacts").glob("*/cells/*/launch.json"):
        if root in launch_path.parents or PREFLIGHT_DIR in launch_path.parents:
            continue
        try:
            launch = json.loads(launch_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if launch.get("mode") == "real" and launch.get("task") in TASKS:
            conflicts.append(launch_path)
    if conflicts:
        raise RuntimeError(f"selected task has prior real evidence: {conflicts[0]}")


def _repository_identity() -> dict[str, Any]:
    files = {}
    for relative in _IDENTITY_FILES:
        path = direct_launch.REPOSITORY_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"runner identity input is absent: {relative}")
        files[relative] = _sha256(path)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=direct_launch.REPOSITORY_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    return {"git_head": head, "files": files, "files_sha256": digest}


def _validate_environment(mode: str) -> str | None:
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError("installed Harbor version differs from 0.21.0")
    if mode == "fake":
        forbidden = sorted(name for name in os.environ if name.endswith("_API_KEY") and os.getenv(name))
        if forbidden:
            raise RuntimeError(f"API credentials are forbidden during no-model preflight: {', '.join(forbidden)}")
        return None
    if os.getenv("TB_DOPPLER_LAUNCH") != DOPPLER_LAUNCH_ID:
        raise RuntimeError("paid launch must enter through the frozen Doppler launcher")
    key = os.environ.pop("OPENAI_API_KEY", None)
    if not key or len(key) < 20:
        raise RuntimeError("Doppler did not inject OPENAI_API_KEY")
    return key


@contextmanager
def _lock() -> Iterator[None]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another additional-campaign launcher holds the exclusive lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _source_bundle() -> Iterator[ExactCommitBundle]:
    raw = os.getenv(direct_launch.LOCAL_SOURCE_ENV)
    if not raw:
        raise RuntimeError(f"{direct_launch.LOCAL_SOURCE_ENV} must name the clean canonical ThinHarness checkout")
    with exact_commit_bundle(Path(raw), THINHARNESS_COMMIT, temporary_prefix=f"{BENCHMARK_ID}-source-") as bundle:
        yield bundle


def _progress(root: Path, mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    path = root / "progress.json"
    source_identity = direct_launch._source_identity(bundle)
    if path.is_file():
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("benchmark_id") != BENCHMARK_ID or value.get("mode") != mode or value.get("planned_cells") != list(EXPECTED_CELLS):
            raise RuntimeError("existing campaign progress differs from the frozen scope")
        if value.get("source_identity") != source_identity:
            raise RuntimeError("existing campaign source identity differs")
        if value.get("runner_identity", {}).get("files_sha256") != identity["files_sha256"]:
            if list(root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl")):
                raise RuntimeError("runner identity changed after a paid request started")
            value["runner_identity"] = identity
        value["status"] = "running"
        value.pop("finished_at", None)
        value.pop("stop", None)
        return value
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SELECTION_PATH, root / "selection.json")
    shutil.copy2(SETTINGS_PATH, root / "settings.json")
    shutil.copy2(RUNNER_SPEC_PATH, root / "runner-spec.json")
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "mode": mode,
        "status": "running",
        "started_at": time.time(),
        "dataset": f"{DATASET_NAME}@{DATASET_DIGEST}",
        "model": MODEL,
        "planned_cells": list(EXPECTED_CELLS),
        "cells": [],
        "source_bundle_sha256": bundle.sha256,
        "source_identity": source_identity,
        "runner_identity": identity,
        "budget": None,
    }


def _write_progress(root: Path, progress: dict[str, Any], event: dict[str, Any] | None = None) -> None:
    progress["updated_at"] = time.time()
    atomic_json(root / "progress.json", progress)
    if event is not None:
        append_jsonl(root / "progress.jsonl", event)
    atomic_json(
        root / "OUTCOME.json",
        {
            "schema_version": 1,
            "benchmark_id": BENCHMARK_ID,
            "mode": progress["mode"],
            "status": progress["status"],
            "checkpointed_cells": len(progress["cells"]),
            "planned_cells": len(EXPECTED_CELLS),
            "stop": progress.get("stop"),
        },
    )


def _checkpoint_is_complete(root: Path, cell_id: str, mode: str) -> dict[str, Any]:
    return direct_validate.validate_cell(
        root / "cells" / cell_id,
        mode=mode,
        cell_id=cell_id,
        expected_cells=EXPECTED_CELLS,
        selection_path=SELECTION_PATH,
        benchmark_id=BENCHMARK_ID,
    )


def _recover(root: Path, progress: dict[str, Any], cell_id: str, mode: str, ledger: DirectBudgetLedger | None) -> str:
    done = {item.get("cell_id") for item in progress["cells"]}
    cell_dir = root / "cells" / cell_id
    if cell_id in done:
        checkpoint = _checkpoint_is_complete(root, cell_id, mode)
        if checkpoint != json.loads((cell_dir / "CHECKPOINT.json").read_text(encoding="utf-8")):
            raise RuntimeError(f"recorded checkpoint differs for {cell_id}")
        return "skip"
    if not cell_dir.exists():
        return "launch"
    marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
    if mode == "real" and marker.is_file() and marker.stat().st_size:
        try:
            checkpoint = _checkpoint_is_complete(root, cell_id, mode)
        except Exception as exc:
            checkpoint = direct_validate.cell_summary(cell_dir, status="consumed_interrupted", real_model_attempted=True)
            checkpoint["recovery_validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
            atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
            progress["cells"].append(checkpoint)
            _write_progress(root, progress, checkpoint)
            if ledger is not None:
                ledger.fail(cell_id, "consumed cell lacks complete usage, identity, receipt, or verifier evidence")
            return "blocked"
        atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
        progress["cells"].append(checkpoint)
        if ledger is not None and ledger.state.get("active_cell") == cell_id:
            ledger.finish_cell(cell_id)
            progress["budget"] = ledger.state
        _write_progress(root, progress, checkpoint)
        return "skip"
    target = root / "infrastructure-attempts" / cell_id / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cell_dir), target)
    if ledger is not None:
        ledger.release_pre_request(cell_id, "pre-request infrastructure attempt preserved")
    progress["stop"] = {"cell_id": cell_id, "reason": "pre-request infrastructure attempt preserved; operator resume required"}
    return "blocked"


def _finish(root: Path, progress: dict[str, Any], status: str, stop: dict[str, Any] | None = None) -> int:
    progress["status"] = status
    progress["finished_at"] = time.time()
    if stop is not None:
        progress["stop"] = stop
    _write_progress(root, progress)
    direct_additional_validate.write_report(root)
    direct_additional_validate.write_hashes(root)
    return 0 if status == "completed" else 2


def run(command: str) -> int:
    if command not in {"preflight", "run"}:
        raise ValueError("command must be preflight or run")
    mode = "fake" if command == "preflight" else "real"
    root = PREFLIGHT_DIR if mode == "fake" else ARTIFACT_DIR
    jobs_dir = PREFLIGHT_JOBS_DIR if mode == "fake" else JOBS_DIR
    credential = _validate_environment(mode)
    _validate_frozen_inputs(root)
    identity = _repository_identity()
    if mode == "real":
        preflight = direct_additional_validate.validate(PREFLIGHT_DIR, expected_mode="fake")
        preflight_identity = preflight.get("runner_identity") or {}
        if preflight_identity.get("files_sha256") != identity["files_sha256"]:
            raise RuntimeError("paid runner identity differs from the finalized no-model preflight")
    with _lock(), _source_bundle() as bundle:
        if (root / "SHA256SUMS.json").is_file():
            try:
                direct_additional_validate.validate(root, expected_mode=mode)
            except RuntimeError:
                pass
            else:
                return 0
        progress = _progress(root, mode, identity, bundle)
        ledger = (
            DirectBudgetLedger(
                root / "budget-ledger.json",
                benchmark_id=BENCHMARK_ID,
                per_cell_cap=PER_CELL_CAP_USD,
                total_cap=TOTAL_CAP_USD,
            )
            if mode == "real"
            else None
        )
        if ledger is not None:
            progress["budget"] = ledger.state
        _write_progress(root, progress)
        for task in TASKS:
            for harness in ("pi", "thinharness"):
                cell_id = f"{task}--{harness}"
                try:
                    _validate_frozen_inputs(root)
                    action = _recover(root, progress, cell_id, mode, ledger)
                    if action == "skip":
                        continue
                    if action == "blocked":
                        return _finish(root, progress, "fail_closed", progress.get("stop"))
                    if ledger is not None:
                        ledger.reserve_cell(cell_id)
                        progress["budget"] = ledger.state
                        _write_progress(root, progress)
                    checkpoint = direct_launch._run_cell(
                        root=root,
                        task=task,
                        harness=harness,
                        mode=mode,
                        api_key=credential,
                        bundle=bundle,
                        identity=identity,
                        benchmark_id=BENCHMARK_ID,
                        jobs_dir=jobs_dir,
                        expected_cells=EXPECTED_CELLS,
                        selection_path=SELECTION_PATH,
                        budget_control=ledger,
                    )
                    atomic_json(root / "cells" / cell_id / "CHECKPOINT.json", checkpoint)
                    if checkpoint.get("status") != "completed":
                        if ledger is not None:
                            ledger.fail(cell_id, f"cell ended without complete receipt: {checkpoint.get('status')}")
                        progress["cells"].append(checkpoint)
                        progress["budget"] = ledger.state if ledger is not None else None
                        _write_progress(root, progress, checkpoint)
                        return _finish(root, progress, "fail_closed", {"cell_id": cell_id, "reason": checkpoint.get("status")})
                    if ledger is not None:
                        ledger.finish_cell(cell_id)
                        progress["budget"] = ledger.state
                    progress["cells"].append(checkpoint)
                    _write_progress(root, progress, checkpoint)
                    if ledger is not None and ledger.blocked is not None:
                        return _finish(root, progress, "fail_closed", ledger.blocked)
                except BaseException as exc:
                    marker = root / "cells" / cell_id / "MODEL_REQUEST_STARTED.jsonl"
                    if ledger is not None:
                        if marker.is_file() and marker.stat().st_size:
                            ledger.fail(cell_id, f"missing usage, identity, hash, receipt, billing, quota, preflight, or cap proof: {exc}")
                        else:
                            ledger.release_pre_request(cell_id, str(exc))
                        progress["budget"] = ledger.state
                    return _finish(
                        root,
                        progress,
                        "fail_closed",
                        {"cell_id": cell_id, "type": type(exc).__name__, "reason": str(exc)},
                    )
        result = _finish(root, progress, "completed")
        direct_additional_validate.validate(root, expected_mode=mode)
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "run"))
    args = parser.parse_args()
    return run(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
