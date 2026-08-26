"""Restart-safe sequential launcher for the 40 direct-OpenAI pairwise cells."""

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

from . import direct_validate
from .direct_behavior_preflight import run_behavior_preflight
from .direct_constants import (
    ARTIFACT_DIR,
    ATTEMPTS,
    BENCHMARK_ID,
    CONCURRENCY,
    DATASET_DIGEST,
    DATASET_NAME,
    EXPECTED_CELLS,
    GATEWAY_TOKEN_ENV,
    GATEWAY_URL_ENV,
    HARBOR_VERSION,
    JOBS_DIR,
    LOCAL_SOURCE_ENV,
    MODEL,
    OPENAI_API_KEY_ENV,
    PREFLIGHT_DIR,
    PREFLIGHT_JOBS_DIR,
    REPOSITORY_ROOT,
    RETRIES,
    RUNS_DIR,
    SELECTION_PATH,
    SETTINGS_PATH,
    SOURCE_BUNDLE_ENV,
    SOURCE_BUNDLE_SHA_ENV,
    TASKS,
    THINHARNESS_COMMIT,
)
from .direct_gateway import GatewayIdentity, run_gateway
from .source_bundle import EXACT_BUNDLE_REF, ExactCommitBundle, exact_commit_bundle

_LOCK = RUNS_DIR / "launch.lock"
_RECOVERY_IDENTITY_FILES = {"tbench/direct_launch.py", "tbench/direct_validate.py", "tbench/source_bundle.py"}
_IDENTITY_FILES = (
    "configs/container-runtime-requirements.txt",
    "configs/direct-openai-20task-selection.json",
    "configs/direct-openai-20task-settings.json",
    "configs/direct-openai-exclusion-proof.json",
    "configs/native-tool-schemas.json",
    "configs/pi-native-tool-schemas.json",
    "configs/pi-subscription-package-lock.json",
    "configs/pi-subscription-package.json",
    "prompts/pi-0.84.2-system-prompt.md",
    "pyproject.toml",
    "scripts/install-direct-pi.sh",
    "scripts/install-direct-thinharness.sh",
    "tbench/container_security.py",
    "tbench/direct_agent.py",
    "tbench/direct_behavior_preflight.py",
    "tbench/direct_constants.py",
    "tbench/direct_container.py",
    "tbench/direct_gateway.py",
    "tbench/direct_launch.py",
    "tbench/direct_validate.py",
    "tbench/pi_subscription_probe.mjs",
    "tbench/source_bundle.py",
    "uv.lock",
)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _read_checkpoint(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"checkpoint is not an object: {path}")
    return value


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def _log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{stamp} {message}"
    print(line, flush=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with (RUNS_DIR / "runner.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _lock() -> Iterator[None]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another direct-OpenAI launcher holds the exclusive lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _source_bundle() -> Iterator[ExactCommitBundle]:
    raw = os.getenv(LOCAL_SOURCE_ENV)
    if not raw:
        raise RuntimeError(f"{LOCAL_SOURCE_ENV} must name a clean canonical ThinHarness checkout containing the pin")
    with exact_commit_bundle(Path(raw), THINHARNESS_COMMIT, temporary_prefix=f"{BENCHMARK_ID}-source-") as bundle:
        yield bundle


def _repository_identity() -> dict[str, Any]:
    files = {}
    for name in _IDENTITY_FILES:
        path = REPOSITORY_ROOT / name
        if not path.is_file():
            raise RuntimeError(f"runner identity input is absent: {name}")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"git_head": head, "files": files, "files_sha256": digest}


def _harbor_command(*, cell_id: str, task: str, harness: str, mode: str, job_name: str, jobs_dir: Path) -> list[str]:
    harbor = shutil.which("harbor")
    if not harbor:
        raise RuntimeError("harbor is not installed; run through uv")
    return [
        harbor,
        "run",
        "--dataset",
        f"{DATASET_NAME}@{DATASET_DIGEST}",
        "--agent",
        "tbench.direct_agent:DirectOpenAIAgent",
        "--model",
        f"openai/{MODEL}",
        "--env",
        "docker",
        "--include-task-name",
        f"terminal-bench/{task}",
        "--n-attempts",
        str(ATTEMPTS),
        "--n-concurrent",
        str(CONCURRENCY),
        "--n-concurrent-agents",
        str(CONCURRENCY),
        "--max-retries",
        str(RETRIES),
        "--timeout-multiplier",
        "1.0",
        "--agent-setup-timeout-multiplier",
        "3.0",
        "--no-force-build",
        "--delete",
        "--yes",
        "--job-name",
        job_name,
        "--jobs-dir",
        str(jobs_dir),
        "--agent-include-logs",
        "*",
        "--agent-kwarg",
        f"harness={harness}",
        "--agent-kwarg",
        f"cell_id={cell_id}",
        "--agent-kwarg",
        f"mode={mode}",
    ]


def _job_name(cell_id: str, mode: str, benchmark_id: str = BENCHMARK_ID) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{benchmark_id}-{mode}-{cell_id}-{stamp}-{uuid.uuid4().hex[:8]}"


def _one_trial(job_dir: Path) -> Path | None:
    if not job_dir.is_dir():
        return None
    trials = [path for path in job_dir.iterdir() if path.is_dir()]
    return trials[0] if len(trials) == 1 else None


def _validate_environment(mode: str) -> str | None:
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError("installed Harbor version differs from 0.21.0")
    if mode == "fake":
        forbidden = [name for name in os.environ if name.endswith("_API_KEY") and os.getenv(name)]
        if forbidden:
            raise RuntimeError(f"API credentials are forbidden during no-model preflight: {', '.join(sorted(forbidden))}")
        return None
    if os.getenv("TB_DOPPLER_LAUNCH") != "tb20-v1":
        raise RuntimeError("real launch must enter through the frozen Doppler launcher boundary")
    key = os.environ.pop(OPENAI_API_KEY_ENV, None)
    if not key or len(key) < 20:
        raise RuntimeError("Doppler did not inject OPENAI_API_KEY")
    return key


def _validate_freshness(root: Path) -> None:
    proof = json.loads((REPOSITORY_ROOT / "configs" / "direct-openai-exclusion-proof.json").read_text(encoding="utf-8"))
    if proof.get("result") != "fresh" or proof.get("selected_tasks") != list(TASKS):
        raise RuntimeError("frozen exclusion proof is absent or differs from the selected tasks")
    conflicts = []
    for cells in (REPOSITORY_ROOT / "artifacts").glob("*/cells"):
        if cells.parent == root:
            continue
        for task in TASKS:
            for path in cells.glob(f"{task}--*"):
                try:
                    mode = json.loads((path / "launch.json").read_text(encoding="utf-8")).get("mode")
                except Exception:
                    mode = "unknown"
                if mode != "fake":
                    conflicts.append(path)
    for task in TASKS:
        conflicts.extend(path for path in (REPOSITORY_ROOT / "jobs").glob(f"*/*-real-{task}--*") if path.parent != JOBS_DIR)
    if conflicts:
        names = ", ".join(str(path.relative_to(REPOSITORY_ROOT)) for path in sorted(set(conflicts)))
        raise RuntimeError(f"selected task has preserved prior real evidence: {names}")


def _validate_preflight_gate() -> None:
    direct_validate.validate_finalized_preflight(PREFLIGHT_DIR)


def _source_identity(bundle: ExactCommitBundle) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_mode": "transient-local-exact-commit-git-bundle",
        "canonical_commit": bundle.target_commit,
        "canonical_tree": bundle.target_tree,
        "canonical_commit_content_sha256": bundle.target_commit_sha256,
        "advertised_ref": bundle.advertised_ref,
        "provenance": {
            "canonical_source_head": bundle.source_head,
            "later_source_head_excluded": bundle.source_head_excluded,
        },
    }


def _initial_progress(mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "mode": mode,
        "status": "running",
        "started_at": time.time(),
        "updated_at": time.time(),
        "dataset": f"{DATASET_NAME}@{DATASET_DIGEST}",
        "model": MODEL,
        "planned_cells": list(EXPECTED_CELLS),
        "cells": [],
        "source_bundle_sha256": bundle.sha256,
        "source_identity": _source_identity(bundle),
        "runner_identity": identity,
    }


def _is_safe_policy_recovery_upgrade(
    root: Path, progress: dict[str, Any], old_identity: dict[str, Any], new_identity: dict[str, Any]
) -> bool:
    old_files = old_identity.get("files") or {}
    new_files = new_identity.get("files") or {}
    if set(old_files) != set(new_files):
        return False
    changed = {name for name in old_files if old_files[name] != new_files[name]}
    stop = progress.get("stop") or {}
    expected_stop = "gateway audit sequence failed for vulnerable-secret--pi"
    if not changed or not changed <= _RECOVERY_IDENTITY_FILES or stop.get("message") != expected_stop:
        return False
    done = {item.get("cell_id") for item in progress.get("cells") or []}
    pending = []
    for cell_id in EXPECTED_CELLS:
        cell_dir = root / "cells" / cell_id
        marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
        if not marker.is_file() or not marker.stat().st_size or cell_id in done:
            continue
        try:
            checkpoint = direct_validate.recover_consumed_cell(cell_dir, mode="real", cell_id=cell_id)
        except (FileNotFoundError, RuntimeError, json.JSONDecodeError):
            return False
        pending.append(checkpoint)
    return len(pending) == 1 and pending[0].get("cell_id") == "vulnerable-secret--pi" and pending[0].get("status") == "model_attempt_failed"


def _legacy_source_identity_is_attested(root: Path, progress: dict[str, Any], bundle: ExactCommitBundle) -> bool:
    old_bundle_sha256 = progress.get("source_bundle_sha256")
    if not isinstance(old_bundle_sha256, str) or len(old_bundle_sha256) != 64:
        return False
    if (
        bundle.target_commit != THINHARNESS_COMMIT
        or bundle.advertised_ref != EXACT_BUNDLE_REF
        or not bundle.source_head_excluded
    ):
        return False
    receipts = 0
    for checkpoint in progress.get("cells") or []:
        cell_id = checkpoint.get("cell_id")
        if not isinstance(cell_id, str) or not cell_id.endswith("--thinharness"):
            continue
        cell_dir = root / "cells" / cell_id
        try:
            launch = _read_checkpoint(cell_dir / "launch.json")
        except (FileNotFoundError, json.JSONDecodeError, RuntimeError):
            return False
        if launch.get("source_bundle_sha256") != old_bundle_sha256:
            return False
        installs = list((cell_dir / "job").glob("*/agent/install-provenance.json"))
        if len(installs) != 1:
            return False
        try:
            install = _read_checkpoint(installs[0])
        except (json.JSONDecodeError, RuntimeError):
            return False
        if (
            install.get("canonical_commit") != THINHARNESS_COMMIT
            or install.get("source_mode") != "transient-local-git-bundle"
            or install.get("source_bundle_sha256") != old_bundle_sha256
        ):
            return False
        receipts += 1
    return receipts > 0


def _load_or_create_progress(
    root: Path, mode: str, identity: dict[str, Any], bundle: ExactCommitBundle
) -> dict[str, Any]:
    progress_path = root / "progress.json"
    if progress_path.is_file():
        value = json.loads(progress_path.read_text(encoding="utf-8"))
        if value.get("mode") != mode or value.get("planned_cells") != list(EXPECTED_CELLS):
            raise RuntimeError("existing progress ledger differs from the frozen run")
        source_identity = _source_identity(bundle)
        old_identity = value.get("runner_identity") or {}
        real_markers = list(root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl"))
        safe_recovery_upgrade = mode == "real" and bool(real_markers) and _is_safe_policy_recovery_upgrade(
            root, value, old_identity, identity
        )
        prior_source_identity = value.get("source_identity")
        if prior_source_identity is None:
            if not safe_recovery_upgrade or not _legacy_source_identity_is_attested(root, value, bundle):
                raise RuntimeError("existing progress lacks an attested canonical source identity")
            value["source_identity"] = source_identity
            value["source_identity_upgrade"] = {
                "prior_transient_bundle_sha256": value.get("source_bundle_sha256"),
                "basis": "completed exact-commit install receipts and narrowly attested consumed-cell runner recovery",
            }
        elif prior_source_identity != source_identity:
            raise RuntimeError("existing progress canonical source identity differs")
        if old_identity.get("files_sha256") != identity["files_sha256"]:
            if mode == "real" and real_markers and not safe_recovery_upgrade:
                raise RuntimeError("runner identity changed after a real model request began")
            value.setdefault("runner_identity_history", []).append(old_identity)
            value["runner_identity"] = identity
        value["status"] = "running"
        value.pop("finished_at", None)
        value.pop("stop", None)
        return value
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SELECTION_PATH, root / "selection.json")
    shutil.copy2(SETTINGS_PATH, root / "settings.json")
    return _initial_progress(mode, identity, bundle)


def _write_progress(root: Path, progress: dict[str, Any], event: dict[str, Any] | None = None) -> None:
    progress["updated_at"] = time.time()
    _atomic_json(root / "progress.json", progress)
    if event is not None:
        _append_jsonl(root / "progress.jsonl", event)
    _atomic_json(
        root / "OUTCOME.json",
        {
            "schema_version": 1,
            "benchmark_id": BENCHMARK_ID,
            "mode": progress["mode"],
            "status": progress["status"],
            "completed_cells": len(progress["cells"]),
            "planned_cells": len(EXPECTED_CELLS),
            "updated_at": progress["updated_at"],
            "stop": progress.get("stop"),
        },
    )


def _recover_consumed_checkpoint(cell_dir: Path, *, cell_id: str, mode: str) -> dict[str, Any]:
    checkpoint_path = cell_dir / "CHECKPOINT.json"
    if checkpoint_path.is_file():
        return _read_checkpoint(checkpoint_path)
    checkpoint = direct_validate.recover_consumed_cell(cell_dir, mode=mode, cell_id=cell_id)
    _atomic_json(checkpoint_path, checkpoint)
    return checkpoint


def _recover_interrupted(root: Path, progress: dict[str, Any], cell_id: str, mode: str) -> bool:
    checkpoint = root / "cells" / cell_id / "CHECKPOINT.json"
    done = {item["cell_id"] for item in progress["cells"]}
    if cell_id in done:
        if not checkpoint.is_file():
            raise RuntimeError(f"progress names {cell_id} but its checkpoint is absent")
        existing = _read_checkpoint(checkpoint)
        if existing.get("status") != "infrastructure_blocker":
            return True
        progress["cells"] = [item for item in progress["cells"] if item.get("cell_id") != cell_id]
        target = root / "infrastructure-attempts" / cell_id / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(checkpoint.parent), target)
        _log(f"preserved recoverable infrastructure attempt at {target}")
        return False
    cell_dir = root / "cells" / cell_id
    if not cell_dir.exists():
        return False
    model_marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
    if mode == "real" and model_marker.is_file() and model_marker.stat().st_size:
        recovered = _recover_consumed_checkpoint(cell_dir, cell_id=cell_id, mode=mode)
        valid_consumed = (
            recovered.get("cell_id") == cell_id
            and recovered.get("real_model_attempted") is True
            and recovered.get("never_rerun") is True
        )
        if not valid_consumed:
            raise RuntimeError(f"consumed checkpoint is invalid for {cell_id}")
        progress["cells"].append(recovered)
        _write_progress(root, progress, recovered)
        _log(f"recovered consumed cell without rerun: {cell_id}")
        return True
    target = root / "infrastructure-attempts" / cell_id / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cell_dir), target)
    _log(f"preserved pre-request infrastructure attempt at {target}")
    return False


def _public_gateway(gateway: GatewayIdentity) -> dict[str, Any]:
    return {
        "base_url": gateway.base_url,
        "port": gateway.port,
        "benchmark_id": gateway.benchmark_id,
        "cell_id": gateway.cell_id,
        "mode": gateway.mode,
        "provider": "OpenAI" if gateway.mode == "real" else "controlled fake",
        "upstream": gateway.upstream if gateway.mode == "real" else None,
        "direct_openai": gateway.mode == "real",
        "bridge": None,
        "ephemeral_token_persisted": False,
    }


def _run_cell(
    *,
    root: Path,
    task: str,
    harness: str,
    mode: str,
    api_key: str | None,
    bundle: ExactCommitBundle,
    identity: dict[str, Any],
    benchmark_id: str = BENCHMARK_ID,
    jobs_dir: Path | None = None,
    expected_cells: tuple[str, ...] = EXPECTED_CELLS,
    selection_path: Path = SELECTION_PATH,
    budget_control: Any | None = None,
) -> dict[str, Any]:
    cell_id = f"{task}--{harness}"
    cell_dir = root / "cells" / cell_id
    cell_dir.mkdir(parents=True)
    selected_jobs_dir = jobs_dir or (PREFLIGHT_JOBS_DIR if mode == "fake" else JOBS_DIR)
    job_name = _job_name(cell_id, mode, benchmark_id)
    job_dir = selected_jobs_dir / job_name
    command = _harbor_command(
        cell_id=cell_id, task=task, harness=harness, mode=mode, job_name=job_name, jobs_dir=selected_jobs_dir
    )
    started = time.time()
    with run_gateway(
        cell_id=cell_id,
        mode=mode,
        evidence_dir=cell_dir,
        api_key=api_key,
        benchmark_id=benchmark_id,
        budget_control=budget_control,
    ) as gateway:
        launch = {
            "schema_version": 1,
            "cell_id": cell_id,
            "task": task,
            "harness": harness,
            "mode": mode,
            "command": command,
            "gateway": _public_gateway(gateway),
            "source_bundle_sha256": bundle.sha256 if harness == "thinharness" else None,
            "runner_identity": identity,
            "credentials": "Doppler key held only by host gateway memory" if mode == "real" else "none; controlled fake",
            "retries": {"model": 0, "transport": 0, "provider": 0, "agent": 0, "harbor": 0},
            "started_at": started,
        }
        _atomic_json(cell_dir / "launch.json", launch)
        environment = os.environ.copy()
        for name in list(environment):
            if name.endswith("_API_KEY") or name.startswith("DOPPLER_") or name == "TB_DOPPLER_LAUNCH":
                environment.pop(name, None)
        environment.update(
            {
                GATEWAY_URL_ENV: gateway.base_url,
                GATEWAY_TOKEN_ENV: gateway.token,
                SOURCE_BUNDLE_ENV: str(bundle.path),
                SOURCE_BUNDLE_SHA_ENV: bundle.sha256,
            }
        )
        with (cell_dir / "harbor.stdout.log").open("w", encoding="utf-8") as stdout, (cell_dir / "harbor.stderr.log").open(
            "w", encoding="utf-8"
        ) as stderr:
            completed = subprocess.run(command, cwd=REPOSITORY_ROOT, env=environment, stdout=stdout, stderr=stderr, check=False)
    finished = time.time()
    if job_dir.is_dir():
        shutil.copytree(job_dir, cell_dir / "job")
    launch["finished_at"] = finished
    launch["harbor_exit_code"] = completed.returncode
    _atomic_json(cell_dir / "launch.json", launch)
    real_attempted = (cell_dir / "MODEL_REQUEST_STARTED.jsonl").is_file()
    credit = (cell_dir / "CREDIT_EXHAUSTED.json").is_file()
    trial = _one_trial(job_dir)
    trial_result = _read_checkpoint(trial / "result.json") if trial is not None and (trial / "result.json").is_file() else {}
    trial_succeeded = (
        completed.returncode == 0
        and trial_result.get("exception_info") is None
        and trial_result.get("agent_result") is not None
    )
    if trial_succeeded:
        checkpoint = direct_validate.validate_cell(
            cell_dir,
            mode=mode,
            cell_id=cell_id,
            expected_cells=expected_cells,
            selection_path=selection_path,
            benchmark_id=benchmark_id,
        )
    elif mode == "real" and real_attempted:
        status = "credit_exhausted" if credit else "model_attempt_failed"
        checkpoint = direct_validate.cell_summary(cell_dir, status=status, real_model_attempted=True)
    else:
        checkpoint = direct_validate.cell_summary(cell_dir, status="infrastructure_blocker", real_model_attempted=False)
    _atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
    return checkpoint


def _finish(root: Path, progress: dict[str, Any], status: str, stop: dict[str, Any] | None = None) -> int:
    progress["status"] = status
    progress["finished_at"] = time.time()
    if stop is not None:
        progress["stop"] = stop
    _write_progress(root, progress)
    direct_validate.write_report(root)
    direct_validate.write_hashes(root)
    _log(f"run outcome: {status}; completed checkpoints: {len(progress['cells'])}/{len(EXPECTED_CELLS)}")
    return 0 if status == "completed" else 2


def run(mode: str) -> int:
    """Run the 40-cell fake preflight or resume the one authorized real run."""
    if mode not in {"preflight", "run"}:
        raise ValueError("mode must be preflight or run")
    gateway_mode = "fake" if mode == "preflight" else "real"
    root = PREFLIGHT_DIR if mode == "preflight" else ARTIFACT_DIR
    credential = _validate_environment(gateway_mode)
    _validate_freshness(root)
    if mode == "run":
        _validate_preflight_gate()
    identity = _repository_identity()
    with _lock(), _source_bundle() as bundle:
        progress = _load_or_create_progress(root, gateway_mode, identity, bundle)
        _write_progress(root, progress)
        if any(item.get("status") == "credit_exhausted" for item in progress["cells"]):
            return _finish(root, progress, "credit_exhausted", {"reason": "prior genuine API billing or quota exhaustion"})
        try:
            for task in TASKS:
                for harness in ("pi", "thinharness"):
                    cell_id = f"{task}--{harness}"
                    if _recover_interrupted(root, progress, cell_id, gateway_mode):
                        if progress["cells"][-1].get("status") == "credit_exhausted":
                            stop = {"cell_id": cell_id, "reason": "prior genuine API billing or quota exhaustion"}
                            return _finish(root, progress, "credit_exhausted", stop)
                        continue
                    _log(f"launching {gateway_mode} cell {cell_id}")
                    checkpoint = _run_cell(
                        root=root,
                        task=task,
                        harness=harness,
                        mode=gateway_mode,
                        api_key=credential,
                        bundle=bundle,
                        identity=identity,
                    )
                    progress["cells"].append(checkpoint)
                    _write_progress(root, progress, checkpoint)
                    if checkpoint["status"] == "credit_exhausted":
                        stop = {"cell_id": cell_id, "reason": "genuine API billing or quota exhaustion"}
                        return _finish(root, progress, "credit_exhausted", stop)
                    if checkpoint["status"] == "infrastructure_blocker":
                        stop = {"cell_id": cell_id, "reason": "pre-request Harbor or runner failure"}
                        return _finish(root, progress, "external_blocker", stop)
        except BaseException as exc:
            progress["status"] = "external_blocker"
            progress["stop"] = {"type": type(exc).__name__, "message": str(exc)}
            progress["finished_at"] = time.time()
            _write_progress(root, progress)
            raise
        if mode == "preflight":
            run_behavior_preflight(root / "behavior-preflight.json")
        result = _finish(root, progress, "completed")
        if mode == "preflight":
            direct_validate.validate_finalized_preflight(root)
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "run"))
    args = parser.parse_args()
    return run(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
