"""Doom-only native ThinHarness v2 supplemental runner."""

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
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import direct_additional_validate, direct_launch, direct_supplement, direct_supplement_finalize, direct_validate
from .constants import REPOSITORY_ROOT
from .direct_budget import BudgetBlocked, DirectBudgetLedger
from .direct_constants import DATASET_DIGEST, DATASET_NAME, HARBOR_VERSION, MODEL, THINHARNESS_COMMIT
from .durable import append_jsonl, atomic_json
from .source_bundle import ExactCommitBundle, exact_commit_bundle

BENCHMARK_ID = "direct-openai-additional-10-thinharness-supplement-v2"
LABEL = "authorized Doom-only supplemental v2 attempt; not an original or v1 cell"
TASK = "make-doom-for-mips"
CELL_ID = f"{TASK}--thinharness"
SUPPLEMENTAL_CELL_ID = f"{CELL_ID}--supplemental-v2-attempt-1"
EXPECTED_CELLS = (CELL_ID,)
EXPECTED_SUPPLEMENTAL_IDS = (SUPPLEMENTAL_CELL_ID,)
SELECTION_PATH = REPOSITORY_ROOT / "configs" / f"{BENCHMARK_ID}-selection.json"
SETTINGS_PATH = REPOSITORY_ROOT / "configs" / f"{BENCHMARK_ID}-settings.json"
RUNNER_SPEC_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-runner-spec.json"
ARTIFACT_DIR = REPOSITORY_ROOT / "artifacts" / BENCHMARK_ID
PREFLIGHT_DIR = REPOSITORY_ROOT / "artifacts" / f"{BENCHMARK_ID}-preflight"
JOBS_DIR = REPOSITORY_ROOT / "jobs" / BENCHMARK_ID
PREFLIGHT_JOBS_DIR = REPOSITORY_ROOT / "jobs" / f"{BENCHMARK_ID}-preflight"
RUNS_DIR = REPOSITORY_ROOT / "runs" / BENCHMARK_ID
REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}.json"
PREFLIGHT_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}-preflight.json"
PER_CELL_CAP_USD = Decimal("10.00")
TOTAL_CAP_USD = Decimal("10.00")
DOPPLER_LAUNCH_ID = "tb-additional-10-thinharness-supplement-v2"
_PRICE = {
    "ordinary_input_tokens": Decimal("5.0"),
    "cached_input_tokens": Decimal("0.5"),
    "cache_write_tokens": Decimal("6.25"),
    "output_tokens": Decimal("30.0"),
}
_MILLION = Decimal(1_000_000)
_LOCK_PATH = RUNS_DIR / "launch.lock"
_IDENTITY_FILES = (
    "configs/container-runtime-requirements.txt",
    "configs/direct-openai-20task-settings.json",
    "configs/direct-openai-additional-10-runner-spec.json",
    "configs/direct-openai-additional-10-thinharness-supplement-v2-selection.json",
    "configs/direct-openai-additional-10-thinharness-supplement-v2-settings.json",
    "configs/native-tool-schemas.json",
    "prompts/pi-0.84.2-system-prompt.md",
    "scripts/direct-openai-additional-10-thinharness-supplement-v2-checks.sh",
    "scripts/direct-openai-additional-10-thinharness-supplement-v2-preflight.sh",
    "scripts/install-direct-thinharness.sh",
    "scripts/run-direct-openai-additional-10-thinharness-supplement-v2.sh",
    "tbench/container_security.py",
    "tbench/direct_agent.py",
    "tbench/direct_budget.py",
    "tbench/direct_container.py",
    "tbench/direct_gateway.py",
    "tbench/direct_launch.py",
    "tbench/direct_supplement_v2.py",
    "tbench/direct_validate.py",
    "tbench/durable.py",
    "tbench/source_bundle.py",
    "uv.lock",
)


class SupplementV2BudgetLedger(DirectBudgetLedger):
    """Keep v2 cap receipts exact without changing the frozen original ledger code."""

    def authorize_request(self, cell_id: str) -> None:
        with self._lock:
            self._blocked()
            if self.state.get("active_cell") != cell_id:
                raise BudgetBlocked("request has no active cell reservation")
            cell_spent = Decimal(self.state["cells"][cell_id]["spent_usd"])
            total_spent = Decimal(self.state["total_spent_usd"])
            committed = total_spent + (self.per_cell_cap - cell_spent)
            if cell_spent >= self.per_cell_cap:
                reason = f"per-cell USD {self.per_cell_cap} cap reached"
                self._fail_locked(cell_id, reason)
                raise BudgetBlocked(reason)
            if committed > self.total_cap:
                reason = f"total USD {self.total_cap} cap reached"
                self._fail_locked(cell_id, reason)
                raise BudgetBlocked(reason)

    def settle_usage(self, cell_id: str, usage: dict[str, Any]) -> Decimal:
        values: dict[str, int] = {}
        for name in _PRICE:
            value = usage.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                self.fail(cell_id, f"missing or invalid usage: {name}")
                raise BudgetBlocked(f"missing or invalid usage: {name}")
            values[name] = value
        cost = sum((Decimal(values[name]) * price / _MILLION for name, price in _PRICE.items()), Decimal(0))
        with self._lock:
            if self.state.get("active_cell") != cell_id:
                raise BudgetBlocked("usage settlement has no active reservation")
            cell = self.state["cells"][cell_id]
            cell_spent = Decimal(cell["spent_usd"]) + cost
            total_spent = Decimal(self.state["total_spent_usd"]) + cost
            cell["spent_usd"] = str(cell_spent)
            self.state["total_spent_usd"] = str(total_spent)
            cell["last_settlement_usd"] = str(cost)
            if cell_spent >= self.per_cell_cap:
                self._fail_locked(cell_id, f"per-cell USD {self.per_cell_cap} cap reached or crossed")
            elif total_spent > self.total_cap:
                self._fail_locked(cell_id, f"total USD {self.total_cap} cap crossed")
            else:
                self._write()
        return cost


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON value is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _selection() -> dict[str, Any]:
    return _read(SELECTION_PATH)


def _settings() -> dict[str, Any]:
    return _read(SETTINGS_PATH)


def _cell() -> dict[str, Any]:
    cells = _selection().get("cells")
    if not isinstance(cells, list) or len(cells) != 1 or not isinstance(cells[0], dict):
        raise RuntimeError("v2 selection must contain exactly one cell")
    return cells[0]


def _validate_prior_evidence() -> None:
    expected = _settings().get("prior_evidence_immutable_sha256")
    if not isinstance(expected, dict) or not expected:
        raise RuntimeError("prior evidence immutability hashes are absent")
    for relative, digest in expected.items():
        path = REPOSITORY_ROOT / str(relative)
        if not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f"published original or v1 evidence changed: {relative}")
    direct_additional_validate.validate_hashes(REPOSITORY_ROOT / "artifacts" / direct_supplement.ORIGINAL_BENCHMARK_ID)
    direct_supplement_finalize.validate_paid_evidence()


def _validate_scope() -> None:
    selection = _selection()
    settings = _settings()
    spec = _read(RUNNER_SPEC_PATH)
    cell = _cell()
    if selection.get("selected") != [cell]:
        raise RuntimeError("v2 selected cell does not equal its sole launch cell")
    if selection.get("benchmark_id") != BENCHMARK_ID or settings.get("benchmark_id") != BENCHMARK_ID:
        raise RuntimeError("v2 namespace identity differs")
    if selection.get("planned_execution_order") != [SUPPLEMENTAL_CELL_ID]:
        raise RuntimeError("v2 order differs from the sole authorized Doom cell")
    if (
        cell.get("task") != TASK
        or cell.get("cell_id") != CELL_ID
        or cell.get("supplemental_cell_id") != SUPPLEMENTAL_CELL_ID
        or cell.get("harness") != "thinharness"
        or cell.get("attempt") != 1
    ):
        raise RuntimeError("v2 scope is not exactly one native ThinHarness Doom attempt")
    encoded = json.dumps(selection, sort_keys=True).lower()
    if "model-extraction-relu-logits" in encoded or '"harness": "pi"' in encoded or "--pi" in encoded:
        raise RuntimeError("v2 selection contains a prohibited task or Pi cell")
    source = selection.get("source_runner_spec") or {}
    if source.get("sha256") != _sha256(RUNNER_SPEC_PATH) or source.get("methodology_identity_sha256") != spec.get(
        "methodology_identity_sha256"
    ):
        raise RuntimeError("v2 source runner specification identity differs")
    refs = {item["task"]: item for item in spec.get("selected_task_refs") or []}
    names = ("task_package_digest", "instruction_sha256", "task_toml_sha256", "task_tree_manifest_sha256")
    original = refs.get(TASK)
    if original is None or any(cell.get(name) != original.get(name) for name in names):
        raise RuntimeError("v2 Doom task package identity differs from the frozen source")
    execution = settings.get("execution") or {}
    model = execution.get("model") or {}
    harbor = execution.get("harbor") or {}
    retries = model.get("retries") or {}
    if (
        execution.get("harnesses") != ["thinharness"]
        or execution.get("thinharness_version") != "0.7.0"
        or execution.get("thinharness_commit") != THINHARNESS_COMMIT
        or execution.get("tool_execution") != "sequential"
        or execution.get("native_tool_schema_sha256") != _sha256(REPOSITORY_ROOT / "configs/native-tool-schemas.json")
        or execution.get("provider_timeout_seconds") != 1800
        or model.get("model") != MODEL
        or model.get("provider") != "OpenAI"
        or model.get("route") != "direct https://api.openai.com/v1/responses"
        or model.get("bridge") is not None
        or model.get("reasoning") != {"effort": "xhigh", "summary": "auto"}
        or model.get("text") != {"verbosity": "low"}
        or model.get("request_timeout_seconds") != 1800
        or set(retries) != {"model", "output", "provider", "tool", "transport"}
        or set(retries.values()) != {0}
        or execution.get("agent_retries") != 0
        or harbor
        != {
            "agent_setup_timeout_multiplier": 3.0,
            "attempts_per_cell": 1,
            "concurrency": 1,
            "environment": "docker",
            "retries": 0,
            "timeout_multiplier": 1.0,
            "version": "0.21.0",
        }
    ):
        raise RuntimeError("v2 execution identity differs")
    prompt = execution.get("prompt") or {}
    if prompt.get("sha256") != _sha256(REPOSITORY_ROOT / str(prompt.get("path"))):
        raise RuntimeError("v2 prompt hash differs")
    budget = settings.get("budget") or {}
    if budget.get("per_cell_cap_usd") != str(PER_CELL_CAP_USD) or budget.get("total_cap_usd") != str(TOTAL_CAP_USD):
        raise RuntimeError("v2 cap differs from the frozen one-cell USD 10 bound")
    _validate_prior_evidence()


def _repository_identity() -> dict[str, Any]:
    files: dict[str, str] = {}
    for relative in _IDENTITY_FILES:
        path = REPOSITORY_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"v2 runner identity input is absent: {relative}")
        files[relative] = _sha256(path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True).stdout.strip()
    return {"git_head": head, "files": files, "files_sha256": _canonical_sha256(files)}


def _validate_environment(mode: str) -> str | None:
    if importlib.metadata.version("harbor") != HARBOR_VERSION:
        raise RuntimeError("installed Harbor version differs from 0.21.0")
    if mode == "fake":
        forbidden = sorted(name for name in os.environ if name.endswith("_API_KEY") and os.getenv(name))
        if forbidden:
            raise RuntimeError("API credentials are forbidden during the v2 no-model preflight")
        return None
    if os.getenv("TB_DOPPLER_LAUNCH") != DOPPLER_LAUNCH_ID:
        raise RuntimeError("v2 paid launch must enter through the frozen Doppler boundary")
    key = os.environ.pop("OPENAI_API_KEY", None)
    if not key or len(key) < 20:
        raise RuntimeError("Doppler did not inject OPENAI_API_KEY")
    return key


@contextmanager
def _lock() -> Iterator[None]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another v2 launcher holds the exclusive lock") from exc
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


def _initial_progress(mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "benchmark_id": BENCHMARK_ID,
        "label": LABEL,
        "mode": mode,
        "status": "running",
        "started_at": time.time(),
        "dataset": f"{DATASET_NAME}@{DATASET_DIGEST}",
        "model": MODEL,
        "planned_cells": [SUPPLEMENTAL_CELL_ID],
        "cells": [],
        "source_bundle_sha256": bundle.sha256,
        "source_identity": direct_launch._source_identity(bundle),
        "runner_identity": identity,
        "budget": None,
    }


def _load_progress(root: Path, mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    path = root / "progress.json"
    source_identity = direct_launch._source_identity(bundle)
    if not path.is_file():
        root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SELECTION_PATH, root / "selection.json")
        shutil.copy2(SETTINGS_PATH, root / "settings.json")
        return _initial_progress(mode, identity, bundle)
    progress = _read(path)
    if (
        progress.get("benchmark_id") != BENCHMARK_ID
        or progress.get("mode") != mode
        or progress.get("planned_cells") != [SUPPLEMENTAL_CELL_ID]
        or progress.get("source_identity") != source_identity
    ):
        raise RuntimeError("existing v2 progress differs from the frozen identity")
    if progress.get("status") == "pre_request_failure":
        raise RuntimeError("prior v2 pre-request failure is preserved and needs new operator authorization")
    prior = progress.get("runner_identity") or {}
    marker = root / "cells" / CELL_ID / "MODEL_REQUEST_STARTED.jsonl"
    if prior.get("files_sha256") != identity["files_sha256"]:
        if marker.is_file() and marker.stat().st_size:
            raise RuntimeError("v2 runner identity changed after its request started")
        progress["runner_identity"] = identity
    progress["status"] = "running"
    progress.pop("finished_at", None)
    progress.pop("stop", None)
    return progress


def _write_progress(root: Path, progress: dict[str, Any], event: dict[str, Any] | None = None) -> None:
    progress["updated_at"] = time.time()
    atomic_json(root / "progress.json", progress)
    if event is not None:
        append_jsonl(root / "progress.jsonl", event)
    atomic_json(
        root / "OUTCOME.json",
        {
            "schema_version": 2,
            "benchmark_id": BENCHMARK_ID,
            "label": LABEL,
            "mode": progress["mode"],
            "status": progress["status"],
            "checkpointed_cells": len(progress["cells"]),
            "planned_cells": 1,
            "stop": progress.get("stop"),
        },
    )


def _decorate(checkpoint: dict[str, Any]) -> dict[str, Any]:
    value = dict(checkpoint)
    value.update(
        {
            "supplemental_cell_id": SUPPLEMENTAL_CELL_ID,
            "supplemental_attempt": 1,
            "supplemental_label": LABEL,
            "task_identity": {
                name: _cell()[name]
                for name in ("task_package_digest", "instruction_sha256", "task_toml_sha256", "task_tree_manifest_sha256")
            },
            "receipt": f"cells/{CELL_ID}/SUPPLEMENTAL_V2_RECEIPT.json",
        }
    )
    return value


def _reproduce_checkpoint(root: Path, mode: str) -> dict[str, Any]:
    return _decorate(
        direct_validate.validate_cell(
            root / "cells" / CELL_ID,
            mode=mode,
            cell_id=CELL_ID,
            expected_cells=EXPECTED_CELLS,
            selection_path=SELECTION_PATH,
            benchmark_id=BENCHMARK_ID,
        )
    )


def _trial(cell_dir: Path) -> Path | None:
    job = cell_dir / "job"
    trials = [path for path in job.iterdir() if path.is_dir()] if job.is_dir() else []
    return trials[0] if len(trials) == 1 else None


def _write_receipt(root: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    cell_dir = root / "cells" / CELL_ID
    paths = [
        cell_dir / "CHECKPOINT.json",
        cell_dir / "launch.json",
        cell_dir / "gateway-identity.json",
        cell_dir / "gateway-audit.jsonl",
        cell_dir / "MODEL_REQUEST_STARTED.jsonl",
    ]
    trial = _trial(cell_dir)
    if trial is not None:
        paths.extend(
            (trial / "result.json", trial / "agent" / "thinharness-direct-result.json", trial / "agent" / "thinharness-events.jsonl")
        )
    receipt = {
        "schema_version": 2,
        "benchmark_id": BENCHMARK_ID,
        "supplemental_cell_id": SUPPLEMENTAL_CELL_ID,
        "cell_id": CELL_ID,
        "attempt": 1,
        "harness": "thinharness",
        "mode": checkpoint.get("mode"),
        "status": checkpoint.get("status"),
        "consumed": checkpoint.get("real_model_attempted") is True,
        "never_rerun": checkpoint.get("never_rerun") is True,
        "task_identity": checkpoint["task_identity"],
        "checkpoint_sha256": _sha256(cell_dir / "CHECKPOINT.json"),
        "trace_sha256": {str(path.relative_to(root)): _sha256(path) for path in paths if path.is_file()},
        "secret_persisted": False,
    }
    atomic_json(cell_dir / "SUPPLEMENTAL_V2_RECEIPT.json", receipt)
    return receipt


def _validate_receipt(root: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    cell_dir = root / "cells" / CELL_ID
    receipt = _read(cell_dir / "SUPPLEMENTAL_V2_RECEIPT.json")
    if (
        receipt.get("benchmark_id") != BENCHMARK_ID
        or receipt.get("supplemental_cell_id") != SUPPLEMENTAL_CELL_ID
        or receipt.get("cell_id") != CELL_ID
        or receipt.get("attempt") != 1
        or receipt.get("harness") != "thinharness"
        or receipt.get("status") != checkpoint.get("status")
        or receipt.get("task_identity") != checkpoint.get("task_identity")
        or receipt.get("checkpoint_sha256") != _sha256(cell_dir / "CHECKPOINT.json")
        or receipt.get("secret_persisted") is not False
    ):
        raise RuntimeError("v2 receipt identity differs")
    traces = receipt.get("trace_sha256")
    if not isinstance(traces, dict) or not traces:
        raise RuntimeError("v2 receipt has no trace hashes")
    for relative, digest in traces.items():
        path = root / str(relative)
        if not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f"v2 receipt trace differs: {relative}")
    return receipt


def _recover(root: Path, progress: dict[str, Any], mode: str, ledger: DirectBudgetLedger | None) -> str:
    if progress["cells"]:
        if [item.get("supplemental_cell_id") for item in progress["cells"]] != [SUPPLEMENTAL_CELL_ID]:
            raise RuntimeError("v2 progress contains an unauthorized checkpoint")
        _validate_receipt(root, progress["cells"][0])
        return "skip"
    cell_dir = root / "cells" / CELL_ID
    if not cell_dir.exists():
        return "launch"
    marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
    try:
        checkpoint = _reproduce_checkpoint(root, mode)
    except Exception as exc:
        if mode == "real" and marker.is_file() and marker.stat().st_size:
            checkpoint = _decorate(direct_validate.cell_summary(cell_dir, status="consumed_interrupted", real_model_attempted=True))
            checkpoint["recovery_validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
            atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
            _write_receipt(root, checkpoint)
            progress["cells"].append(checkpoint)
            if ledger is not None:
                ledger.fail(CELL_ID, "consumed v2 cell lacks complete evidence")
                progress["budget"] = ledger.state
            _write_progress(root, progress, checkpoint)
            return "blocked"
        progress["status"] = "pre_request_failure"
        progress["stop"] = {"cell_id": SUPPLEMENTAL_CELL_ID, "reason": str(exc)}
        _write_progress(root, progress)
        return "blocked"
    recorded = cell_dir / "CHECKPOINT.json"
    if recorded.is_file() and _read(recorded) != checkpoint:
        raise RuntimeError("v2 checkpoint mismatch")
    atomic_json(recorded, checkpoint)
    _write_receipt(root, checkpoint)
    progress["cells"].append(checkpoint)
    if ledger is not None and ledger.state.get("active_cell") == CELL_ID and checkpoint.get("status") == "completed":
        ledger.finish_cell(CELL_ID)
        progress["budget"] = ledger.state
    _write_progress(root, progress, checkpoint)
    return "skip" if checkpoint.get("status") == "completed" else "blocked"


def _display_root(root: Path) -> str:
    return str(root.relative_to(REPOSITORY_ROOT)) if root.is_relative_to(REPOSITORY_ROOT) else str(root)


def build_report(root: Path) -> dict[str, Any]:
    progress = _read(root / "progress.json")
    cells = progress.get("cells") or []
    usage_names = (
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    usage = {name: sum(item.get("usage", {}).get(name, 0) for item in cells) for name in usage_names}
    api_cost = sum((Decimal(str((item.get("cost") or {}).get("api_equivalent_total", 0))) for item in cells), Decimal(0))
    rewards = [Decimal(str(item["reward"])) for item in cells if isinstance(item.get("reward"), int | float)]
    marker = root / "cells" / CELL_ID / "MODEL_REQUEST_STARTED.jsonl"
    return {
        "schema_version": 2,
        "benchmark_id": BENCHMARK_ID,
        "label": LABEL,
        "mode": progress.get("mode"),
        "status": progress.get("status"),
        "planned_cells": [SUPPLEMENTAL_CELL_ID],
        "checkpointed_cells": len(cells),
        "cells": cells,
        "aggregate": {
            "usage": usage,
            "api_equivalent_cost_usd": str(api_cost),
            "upstream_requests": len(marker.read_text(encoding="utf-8").splitlines()) if marker.is_file() else 0,
            "reward_sum": str(sum(rewards, Decimal(0))),
            "reward_count": len(rewards),
        },
        "budget": progress.get("budget"),
        "runner_identity": progress.get("runner_identity"),
        "source_identity": progress.get("source_identity"),
        "prior_evidence_immutable": True,
        "stop": progress.get("stop"),
        "reproduce": {
            "report": f"uv run python -m tbench.direct_supplement_v2 validate {_display_root(root)} --mode {progress.get('mode')}",
            "checks": "./scripts/direct-openai-additional-10-thinharness-supplement-v2-checks.sh",
        },
    }


def _write_report(root: Path) -> dict[str, Any]:
    report = build_report(root)
    atomic_json(root / "SUMMARY.json", report)
    atomic_json(PREFLIGHT_REPORT_PATH if report["mode"] == "fake" else REPORT_PATH, report)
    return report


def _write_hashes(root: Path) -> None:
    atomic_json(
        root / "SHA256SUMS.json",
        {
            str(path.relative_to(root)): _sha256(path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "SHA256SUMS.json"
        },
    )


def _validate_hashes(root: Path) -> None:
    expected = _read(root / "SHA256SUMS.json")
    actual = {
        str(path.relative_to(root)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file() and path.name != "SHA256SUMS.json"
    }
    if expected != actual:
        raise RuntimeError("v2 artifact SHA256 manifest differs")


def validate(root: Path, *, expected_mode: str) -> dict[str, Any]:
    _validate_scope()
    progress = _read(root / "progress.json")
    if (
        progress.get("benchmark_id") != BENCHMARK_ID
        or progress.get("mode") != expected_mode
        or progress.get("status") != "completed"
        or progress.get("planned_cells") != [SUPPLEMENTAL_CELL_ID]
        or [item.get("supplemental_cell_id") for item in progress.get("cells") or []] != [SUPPLEMENTAL_CELL_ID]
    ):
        raise RuntimeError("v2 finalized progress differs")
    if (root / "selection.json").read_bytes() != SELECTION_PATH.read_bytes() or (
        root / "settings.json"
    ).read_bytes() != SETTINGS_PATH.read_bytes():
        raise RuntimeError("v2 namespaced selection or settings differ")
    cell_root = root / "cells"
    if sorted(path.name for path in cell_root.iterdir() if path.is_dir()) != [CELL_ID]:
        raise RuntimeError("v2 artifact contains a missing or unauthorized cell")
    checkpoint = _reproduce_checkpoint(root, expected_mode)
    if _read(cell_root / CELL_ID / "CHECKPOINT.json") != checkpoint or progress["cells"] != [checkpoint]:
        raise RuntimeError("v2 checkpoint does not reproduce")
    _validate_receipt(root, checkpoint)
    marker = cell_root / CELL_ID / "MODEL_REQUEST_STARTED.jsonl"
    if expected_mode == "fake" and marker.exists():
        raise RuntimeError("v2 no-model preflight made an upstream request")
    if expected_mode == "real" and (not marker.is_file() or not marker.stat().st_size):
        raise RuntimeError("v2 paid cell lacks its consuming request marker")
    report = build_report(root)
    report_path = PREFLIGHT_REPORT_PATH if expected_mode == "fake" else REPORT_PATH
    if _read(root / "SUMMARY.json") != report or _read(report_path) != report:
        raise RuntimeError("v2 report does not reproduce")
    _validate_hashes(root)
    _validate_prior_evidence()
    return report


def _finish(root: Path, progress: dict[str, Any], status: str, stop: dict[str, Any] | None = None) -> int:
    progress["status"] = status
    progress["finished_at"] = time.time()
    if stop is not None:
        progress["stop"] = stop
    _write_progress(root, progress)
    _write_report(root)
    _write_hashes(root)
    _validate_prior_evidence()
    return 0 if status == "completed" else 2


def run(command: str) -> int:
    if command not in {"preflight", "run"}:
        raise ValueError("command must be preflight or run")
    mode = "fake" if command == "preflight" else "real"
    root = PREFLIGHT_DIR if mode == "fake" else ARTIFACT_DIR
    jobs_dir = PREFLIGHT_JOBS_DIR if mode == "fake" else JOBS_DIR
    credential = _validate_environment(mode)
    _validate_scope()
    identity = _repository_identity()
    if mode == "real":
        preflight = validate(PREFLIGHT_DIR, expected_mode="fake")
        if (preflight.get("runner_identity") or {}).get("files_sha256") != identity["files_sha256"]:
            raise RuntimeError("paid v2 runner identity differs from the finalized no-model preflight")
    with _lock(), _source_bundle() as bundle:
        if (root / "SHA256SUMS.json").is_file():
            validate(root, expected_mode=mode)
            return 0
        progress = _load_progress(root, mode, identity, bundle)
        ledger = (
            SupplementV2BudgetLedger(
                root / "budget-ledger.json", benchmark_id=BENCHMARK_ID, per_cell_cap=PER_CELL_CAP_USD, total_cap=TOTAL_CAP_USD
            )
            if mode == "real"
            else None
        )
        if ledger is not None:
            progress["budget"] = ledger.state
        _write_progress(root, progress)
        try:
            action = _recover(root, progress, mode, ledger)
            if action == "blocked":
                return _finish(root, progress, "fail_closed", progress.get("stop"))
            if action == "skip":
                if progress["cells"] and progress["cells"][0].get("status") == "completed":
                    result = _finish(root, progress, "completed")
                    validate(root, expected_mode=mode)
                    return result
                return _finish(root, progress, "fail_closed", {"cell_id": SUPPLEMENTAL_CELL_ID, "reason": "consumed incomplete cell"})
            if ledger is not None:
                ledger.reserve_cell(CELL_ID)
                progress["budget"] = ledger.state
                _write_progress(root, progress)
            checkpoint = _decorate(
                direct_launch._run_cell(
                    root=root,
                    task=TASK,
                    harness="thinharness",
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
            )
            atomic_json(root / "cells" / CELL_ID / "CHECKPOINT.json", checkpoint)
            _write_receipt(root, checkpoint)
            progress["cells"].append(checkpoint)
            if checkpoint.get("status") == "completed":
                if ledger is not None:
                    ledger.finish_cell(CELL_ID)
                    progress["budget"] = ledger.state
            elif ledger is not None:
                ledger.fail(CELL_ID, f"v2 cell ended without complete evidence: {checkpoint.get('status')}")
                progress["budget"] = ledger.state
            _write_progress(root, progress, checkpoint)
            if checkpoint.get("status") != "completed":
                return _finish(root, progress, "fail_closed", {"cell_id": SUPPLEMENTAL_CELL_ID, "reason": str(checkpoint.get("status"))})
            if ledger is not None and ledger.blocked is not None:
                return _finish(root, progress, "cap_exceeded", ledger.blocked)
            result = _finish(root, progress, "completed")
            validate(root, expected_mode=mode)
            return result
        except BaseException as exc:
            marker = root / "cells" / CELL_ID / "MODEL_REQUEST_STARTED.jsonl"
            if marker.is_file() and marker.stat().st_size and not progress["cells"]:
                cell_dir = root / "cells" / CELL_ID
                checkpoint = _decorate(direct_validate.cell_summary(cell_dir, status="consumed_interrupted", real_model_attempted=True))
                checkpoint["recovery_validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
                atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
                _write_receipt(root, checkpoint)
                progress["cells"].append(checkpoint)
                _write_progress(root, progress, checkpoint)
            if ledger is not None:
                if marker.is_file() and marker.stat().st_size:
                    ledger.fail(CELL_ID, f"fail closed after consumed v2 request: {exc}")
                else:
                    ledger.release_pre_request(CELL_ID, str(exc))
                progress["budget"] = ledger.state
            return _finish(
                root,
                progress,
                "fail_closed" if marker.is_file() and marker.stat().st_size else "pre_request_failure",
                {"cell_id": SUPPLEMENTAL_CELL_ID, "type": type(exc).__name__, "reason": str(exc)},
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    subparsers.add_parser("run")
    subparsers.add_parser("check")
    validation = subparsers.add_parser("validate")
    validation.add_argument("root", type=Path)
    validation.add_argument("--mode", choices=("fake", "real"), required=True)
    args = parser.parse_args()
    if args.command == "validate":
        validate(args.root, expected_mode=args.mode)
        return 0
    if args.command == "check":
        _validate_scope()
        _repository_identity()
        print("v2 Doom-only scope, identities, cap, credentials, and immutable prior evidence passed")
        return 0
    return run(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
