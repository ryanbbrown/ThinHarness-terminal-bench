"""ThinHarness-only supplemental runner for two authorized comparison cells."""

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
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import direct_additional_validate, direct_launch, direct_validate
from .constants import REPOSITORY_ROOT
from .direct_budget import DirectBudgetLedger
from .direct_constants import DATASET_DIGEST, DATASET_NAME, HARBOR_VERSION, MODEL, THINHARNESS_COMMIT
from .durable import append_jsonl, atomic_json
from .source_bundle import ExactCommitBundle, exact_commit_bundle

BENCHMARK_ID = "direct-openai-additional-10-thinharness-supplement-v1"
ORIGINAL_BENCHMARK_ID = "direct-openai-additional-10-pairwise"
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
TOTAL_CAP_USD = Decimal("20.00")
DOPPLER_LAUNCH_ID = "tb-additional-10-thinharness-supplement-v1"
EXPECTED_CELL_IDS = (
    "model-extraction-relu-logits--thinharness",
    "make-doom-for-mips--thinharness",
)
EXPECTED_SUPPLEMENTAL_IDS = tuple(f"{cell_id}--supplemental-attempt-1" for cell_id in EXPECTED_CELL_IDS)
POLICY_RESPONSE = {
    "error": {
        "code": "cyber_policy",
        "message": (
            "This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. "
            "To get authorized for security work, join the Trusted Access for Cyber program: https://chatgpt.com/cyber"
        ),
        "param": None,
        "type": "invalid_request",
    }
}
_LOCK_PATH = RUNS_DIR / "launch.lock"
_IDENTITY_FILES = (
    "configs/container-runtime-requirements.txt",
    "configs/direct-openai-20task-settings.json",
    "configs/direct-openai-additional-10-runner-spec.json",
    "configs/direct-openai-additional-10-thinharness-supplement-v1-selection.json",
    "configs/direct-openai-additional-10-thinharness-supplement-v1-settings.json",
    "configs/native-tool-schemas.json",
    "prompts/pi-0.84.2-system-prompt.md",
    "scripts/direct-openai-additional-10-thinharness-supplement-v1-checks.sh",
    "scripts/direct-openai-additional-10-thinharness-supplement-v1-preflight.sh",
    "scripts/install-direct-thinharness.sh",
    "scripts/run-direct-openai-additional-10-thinharness-supplement-v1.sh",
    "tbench/container_security.py",
    "tbench/direct_agent.py",
    "tbench/direct_budget.py",
    "tbench/direct_container.py",
    "tbench/direct_gateway.py",
    "tbench/direct_launch.py",
    "tbench/direct_supplement.py",
    "tbench/direct_validate.py",
    "tbench/durable.py",
    "tbench/source_bundle.py",
    "uv.lock",
)


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


def _cells() -> tuple[dict[str, Any], ...]:
    values = _selection().get("cells")
    if not isinstance(values, list) or len(values) != 2 or not all(isinstance(item, dict) for item in values):
        raise RuntimeError("supplemental selection must contain exactly two cells")
    return tuple(values)


def _cell_map() -> dict[str, dict[str, Any]]:
    return {str(item["cell_id"]): item for item in _cells()}


def _validate_original_evidence() -> None:
    settings = _settings()
    expected = settings.get("original_evidence_immutable_sha256")
    if not isinstance(expected, dict) or not expected:
        raise RuntimeError("original evidence immutability hashes are absent")
    for relative, digest in expected.items():
        path = REPOSITORY_ROOT / str(relative)
        if not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f"original frozen campaign evidence changed: {relative}")
    direct_additional_validate.validate_hashes(REPOSITORY_ROOT / "artifacts" / ORIGINAL_BENCHMARK_ID)


def _validate_scope() -> None:
    selection = _selection()
    settings = _settings()
    spec = _read(RUNNER_SPEC_PATH)
    cells = _cells()
    if selection.get("selected") != list(cells):
        raise RuntimeError("supplemental validation selection does not map base task/harness cells")
    if selection.get("benchmark_id") != BENCHMARK_ID or settings.get("benchmark_id") != BENCHMARK_ID:
        raise RuntimeError("supplemental namespace identity differs")
    if selection.get("planned_execution_order") != list(EXPECTED_SUPPLEMENTAL_IDS):
        raise RuntimeError("supplemental order or IDs differ")
    if tuple(str(item.get("cell_id")) for item in cells) != EXPECTED_CELL_IDS:
        raise RuntimeError("supplemental base cell order differs")
    if tuple(str(item.get("supplemental_cell_id")) for item in cells) != EXPECTED_SUPPLEMENTAL_IDS:
        raise RuntimeError("supplemental attempt IDs differ")
    if any(item.get("harness") != "thinharness" or item.get("attempt") != 1 for item in cells):
        raise RuntimeError("supplemental scope is not ThinHarness-only attempt 1")
    spec_hash = (selection.get("source_runner_spec") or {}).get("sha256")
    if spec_hash != _sha256(RUNNER_SPEC_PATH):
        raise RuntimeError("source runner specification hash differs")
    refs = {item["task"]: item for item in spec.get("selected_task_refs") or []}
    names = ("task_package_digest", "instruction_sha256", "task_toml_sha256", "task_tree_manifest_sha256")
    for cell in cells:
        original = refs.get(cell.get("task"))
        if original is None or any(cell.get(name) != original.get(name) for name in names):
            raise RuntimeError(f"supplemental task identity differs: {cell.get('task')}")
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
        or model.get("reasoning") != {"effort": "xhigh", "summary": "auto"}
        or model.get("text") != {"verbosity": "low"}
        or model.get("request_timeout_seconds") != 1800
        or set(retries) != {"model", "output", "provider", "tool", "transport"}
        or set(retries.values()) != {0}
        or execution.get("agent_retries") != 0
        or harbor.get("version") != "0.21.0"
        or harbor.get("attempts_per_cell") != 1
        or harbor.get("concurrency") != 1
        or harbor.get("retries") != 0
    ):
        raise RuntimeError("supplemental execution identity differs from the published setup")
    prompt = execution.get("prompt") or {}
    if prompt.get("sha256") != _sha256(REPOSITORY_ROOT / str(prompt.get("path"))):
        raise RuntimeError("supplemental prompt hash differs")
    budget = settings.get("budget") or {}
    if budget.get("per_cell_cap_usd") != str(PER_CELL_CAP_USD) or budget.get("total_cap_usd") != str(TOTAL_CAP_USD):
        raise RuntimeError("supplemental cap differs from the frozen USD 10/USD 20 authorization")
    _validate_original_evidence()


def _repository_identity() -> dict[str, Any]:
    files: dict[str, str] = {}
    for relative in _IDENTITY_FILES:
        path = REPOSITORY_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"runner identity input is absent: {relative}")
        files[relative] = _sha256(path)
    digest = _canonical_sha256(files)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True).stdout.strip()
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
        raise RuntimeError("supplemental paid launch must enter through the frozen Doppler boundary")
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
            raise RuntimeError("another supplemental launcher holds the exclusive lock") from exc
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


def _log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{stamp} {message}"
    print(line, flush=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / "runner.log"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _initial_progress(mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "label": "authorized supplemental reruns; not original campaign cells",
        "original_benchmark_id": ORIGINAL_BENCHMARK_ID,
        "mode": mode,
        "status": "running",
        "started_at": time.time(),
        "dataset": f"{DATASET_NAME}@{DATASET_DIGEST}",
        "model": MODEL,
        "planned_cells": list(EXPECTED_SUPPLEMENTAL_IDS),
        "cells": [],
        "source_bundle_sha256": bundle.sha256,
        "source_identity": direct_launch._source_identity(bundle),
        "runner_identity": identity,
        "budget": None,
    }


def _load_progress(root: Path, mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    path = root / "progress.json"
    source_identity = direct_launch._source_identity(bundle)
    if path.is_file():
        progress = _read(path)
        if (
            progress.get("benchmark_id") != BENCHMARK_ID
            or progress.get("mode") != mode
            or progress.get("planned_cells") != list(EXPECTED_SUPPLEMENTAL_IDS)
        ):
            raise RuntimeError("existing supplemental progress differs from the frozen scope")
        if progress.get("source_identity") != source_identity:
            raise RuntimeError("existing supplemental source identity differs")
        prior = progress.get("runner_identity") or {}
        if prior.get("files_sha256") != identity["files_sha256"]:
            if list(root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl")):
                raise RuntimeError("supplemental runner identity changed after a request started")
            progress["runner_identity"] = identity
        progress["status"] = "running"
        progress.pop("finished_at", None)
        progress.pop("stop", None)
        return progress
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SELECTION_PATH, root / "selection.json")
    shutil.copy2(SETTINGS_PATH, root / "settings.json")
    return _initial_progress(mode, identity, bundle)


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
            "label": progress.get("label", "authorized supplemental reruns; not original campaign cells"),
            "mode": progress["mode"],
            "status": progress["status"],
            "checkpointed_cells": len(progress["cells"]),
            "planned_cells": 2,
            "stop": progress.get("stop"),
        },
    )


def _decorate(checkpoint: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    value = dict(checkpoint)
    value.update(
        {
            "supplemental_cell_id": cell["supplemental_cell_id"],
            "supplemental_attempt": 1,
            "supplemental_label": "authorized supplemental rerun; not an original campaign cell",
            "task_identity": {
                name: cell[name]
                for name in (
                    "task_package_digest",
                    "instruction_sha256",
                    "task_toml_sha256",
                    "task_tree_manifest_sha256",
                )
            },
            "receipt": f"cells/{cell['cell_id']}/SUPPLEMENTAL_RECEIPT.json",
        }
    )
    return value


def _reproduce_checkpoint(root: Path, cell: dict[str, Any], mode: str) -> dict[str, Any]:
    base = direct_validate.validate_cell(
        root / "cells" / cell["cell_id"],
        mode=mode,
        cell_id=cell["cell_id"],
        expected_cells=EXPECTED_CELL_IDS,
        selection_path=SELECTION_PATH,
        benchmark_id=BENCHMARK_ID,
    )
    return _decorate(base, cell)


def _trial(cell_dir: Path) -> Path | None:
    job = cell_dir / "job"
    if not job.is_dir():
        return None
    trials = [path for path in job.iterdir() if path.is_dir()]
    return trials[0] if len(trials) == 1 else None


def _write_receipt(root: Path, cell: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
    cell_dir = root / "cells" / cell["cell_id"]
    paths = [
        cell_dir / "CHECKPOINT.json",
        cell_dir / "launch.json",
        cell_dir / "gateway-identity.json",
        cell_dir / "gateway-audit.jsonl",
        cell_dir / "MODEL_REQUEST_STARTED.jsonl",
        cell_dir / "POLICY_REFUSAL.json",
    ]
    trial = _trial(cell_dir)
    if trial is not None:
        paths.extend(
            (trial / "result.json", trial / "agent" / "thinharness-direct-result.json", trial / "agent" / "thinharness-events.jsonl")
        )
    traces = {str(path.relative_to(root)): _sha256(path) for path in paths if path.is_file()}
    receipt = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "supplemental_cell_id": cell["supplemental_cell_id"],
        "cell_id": cell["cell_id"],
        "attempt": 1,
        "harness": "thinharness",
        "mode": checkpoint.get("mode"),
        "status": checkpoint.get("status"),
        "consumed": checkpoint.get("real_model_attempted") is True,
        "never_rerun": checkpoint.get("never_rerun") is True,
        "task_identity": checkpoint["task_identity"],
        "checkpoint_sha256": _sha256(cell_dir / "CHECKPOINT.json"),
        "trace_sha256": traces,
        "secret_persisted": False,
    }
    atomic_json(cell_dir / "SUPPLEMENTAL_RECEIPT.json", receipt)
    return receipt


def _validate_receipt(root: Path, cell: dict[str, Any], checkpoint: dict[str, Any]) -> dict[str, Any]:
    cell_dir = root / "cells" / cell["cell_id"]
    receipt = _read(cell_dir / "SUPPLEMENTAL_RECEIPT.json")
    if (
        receipt.get("benchmark_id") != BENCHMARK_ID
        or receipt.get("supplemental_cell_id") != cell["supplemental_cell_id"]
        or receipt.get("cell_id") != cell["cell_id"]
        or receipt.get("attempt") != 1
        or receipt.get("harness") != "thinharness"
        or receipt.get("status") != checkpoint.get("status")
        or receipt.get("task_identity") != checkpoint.get("task_identity")
        or receipt.get("checkpoint_sha256") != _sha256(cell_dir / "CHECKPOINT.json")
        or receipt.get("secret_persisted") is not False
    ):
        raise RuntimeError(f"supplemental receipt identity differs: {cell['cell_id']}")
    traces = receipt.get("trace_sha256")
    if not isinstance(traces, dict) or not traces:
        raise RuntimeError(f"supplemental receipt has no trace hashes: {cell['cell_id']}")
    for relative, digest in traces.items():
        path = root / str(relative)
        if not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f"supplemental receipt trace differs: {relative}")
    return receipt


def _policy_refusal(checkpoint: dict[str, Any]) -> bool:
    failure = checkpoint.get("model_attempt_failure") or {}
    return failure.get("response") == POLICY_RESPONSE and failure.get("credit_exhausted") is False


def _write_policy_refusal(root: Path, cell: dict[str, Any], checkpoint: dict[str, Any]) -> None:
    failure = checkpoint.get("model_attempt_failure") or {}
    atomic_json(
        root / "cells" / cell["cell_id"] / "POLICY_REFUSAL.json",
        {
            "schema_version": 1,
            "benchmark_id": BENCHMARK_ID,
            "supplemental_cell_id": cell["supplemental_cell_id"],
            "never_retry": True,
            "repeats_original": True,
            "response": failure.get("response"),
            "response_sha256": failure.get("response_sha256"),
            "original_response_sha256": _canonical_sha256(POLICY_RESPONSE),
        },
    )


def _recover(
    root: Path,
    progress: dict[str, Any],
    cell: dict[str, Any],
    mode: str,
    ledger: DirectBudgetLedger | None,
) -> str:
    supplemental_id = str(cell["supplemental_cell_id"])
    cell_id = str(cell["cell_id"])
    done = {item.get("supplemental_cell_id") for item in progress["cells"]}
    cell_dir = root / "cells" / cell_id
    if supplemental_id in done:
        recorded = _read(cell_dir / "CHECKPOINT.json")
        _validate_receipt(root, cell, recorded)
        return "skip"
    if not cell_dir.exists():
        return "launch"
    marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
    try:
        checkpoint = _reproduce_checkpoint(root, cell, mode)
    except Exception as exc:
        if mode == "real" and marker.is_file() and marker.stat().st_size:
            checkpoint = _decorate(direct_validate.cell_summary(cell_dir, status="consumed_interrupted", real_model_attempted=True), cell)
            checkpoint["recovery_validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
            atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
            _write_receipt(root, cell, checkpoint)
            progress["cells"].append(checkpoint)
            _write_progress(root, progress, checkpoint)
            if ledger is not None:
                ledger.fail(cell_id, "consumed cell lacks complete usage, identity, hash, receipt, or Harbor evidence")
                progress["budget"] = ledger.state
            return "blocked"
        target = root / "infrastructure-attempts" / cell_id / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cell_dir), target)
        if ledger is not None:
            ledger.release_pre_request(cell_id, str(exc))
            progress["budget"] = ledger.state
        progress["stop"] = {"cell_id": supplemental_id, "reason": "pre-request attempt preserved; operator resume required"}
        return "blocked"
    recorded_path = cell_dir / "CHECKPOINT.json"
    if recorded_path.is_file() and _read(recorded_path) != checkpoint:
        raise RuntimeError(f"supplemental checkpoint mismatch: {cell_id}")
    atomic_json(recorded_path, checkpoint)
    if _policy_refusal(checkpoint):
        _write_policy_refusal(root, cell, checkpoint)
    _write_receipt(root, cell, checkpoint)
    progress["cells"].append(checkpoint)
    if ledger is not None and ledger.state.get("active_cell") == cell_id and checkpoint.get("status") == "completed":
        ledger.finish_cell(cell_id)
        progress["budget"] = ledger.state
    _write_progress(root, progress, checkpoint)
    return "skip" if checkpoint.get("status") == "completed" else "blocked"


def _audit_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in root.glob("cells/*/gateway-audit.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


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
    usage = {name: 0 for name in usage_names}
    api_cost = Decimal(0)
    rewards: list[Decimal] = []
    statuses: dict[str, int] = {}
    for cell in cells:
        for name in usage:
            value = (cell.get("usage") or {}).get(name)
            if isinstance(value, int):
                usage[name] += value
        value = (cell.get("cost") or {}).get("api_equivalent_total")
        if isinstance(value, int | float):
            api_cost += Decimal(str(value))
        reward = cell.get("reward")
        if isinstance(reward, int | float):
            rewards.append(Decimal(str(reward)))
        status = cell.get("status")
        if isinstance(status, str):
            statuses[status] = statuses.get(status, 0) + 1
    audits = _audit_records(root)
    successful = [item for item in audits if item.get("status") == 200]
    provider_costs = [
        Decimal(str(actual)) for item in successful if isinstance(actual := (item.get("cost_usd") or {}).get("actual_cash"), int | float)
    ]
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "label": "authorized supplemental reruns; not original campaign cells",
        "original_benchmark_id": ORIGINAL_BENCHMARK_ID,
        "mode": progress.get("mode"),
        "status": progress.get("status"),
        "planned_cells": list(EXPECTED_SUPPLEMENTAL_IDS),
        "checkpointed_cells": len(cells),
        "cells": cells,
        "aggregate": {
            "usage": usage,
            "api_equivalent_cost_usd": str(api_cost),
            "provider_reported_cost_usd": str(sum(provider_costs, Decimal(0))) if provider_costs else None,
            "provider_reported_cost_observations": len(provider_costs),
            "provider_reported_cost_complete": len(provider_costs) == len(successful) and bool(successful),
            "successful_upstream_requests": len(successful) if progress.get("mode") == "real" else 0,
            "upstream_requests": sum(
                len(path.read_text(encoding="utf-8").splitlines()) for path in root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl")
            ),
            "reward_sum": str(sum(rewards, Decimal(0))),
            "reward_count": len(rewards),
            "cell_status_counts": statuses,
        },
        "budget": progress.get("budget"),
        "runner_identity": progress.get("runner_identity"),
        "source_identity": progress.get("source_identity"),
        "original_evidence_immutable": True,
        "stop": progress.get("stop"),
        "reproduce": {
            "report": f"uv run python -m tbench.direct_supplement validate {_display_root(root)} --mode {progress.get('mode')}",
            "checks": "./scripts/direct-openai-additional-10-thinharness-supplement-v1-checks.sh",
        },
    }


def _write_report(root: Path) -> dict[str, Any]:
    report = build_report(root)
    atomic_json(root / "SUMMARY.json", report)
    atomic_json(PREFLIGHT_REPORT_PATH if report["mode"] == "fake" else REPORT_PATH, report)
    return report


def _write_hashes(root: Path) -> dict[str, str]:
    hashes = {
        str(path.relative_to(root)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file() and path.name != "SHA256SUMS.json"
    }
    atomic_json(root / "SHA256SUMS.json", hashes)
    return hashes


def _validate_hashes(root: Path) -> None:
    expected = _read(root / "SHA256SUMS.json")
    actual = {
        str(path.relative_to(root)): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file() and path.name != "SHA256SUMS.json"
    }
    if expected != actual:
        raise RuntimeError("supplemental artifact SHA256 manifest differs")


def validate(root: Path, *, expected_mode: str) -> dict[str, Any]:
    _validate_scope()
    progress = _read(root / "progress.json")
    if (
        progress.get("benchmark_id") != BENCHMARK_ID
        or progress.get("mode") != expected_mode
        or progress.get("status") != "completed"
        or progress.get("planned_cells") != list(EXPECTED_SUPPLEMENTAL_IDS)
    ):
        raise RuntimeError("supplemental finalized progress differs")
    if (root / "selection.json").read_bytes() != SELECTION_PATH.read_bytes() or (
        root / "settings.json"
    ).read_bytes() != SETTINGS_PATH.read_bytes():
        raise RuntimeError("supplemental namespaced selection or settings differ")
    cells = _cells()
    if [item.get("supplemental_cell_id") for item in progress.get("cells") or []] != list(EXPECTED_SUPPLEMENTAL_IDS):
        raise RuntimeError("supplemental checkpoint order differs")
    actual_dirs = sorted(path.name for path in (root / "cells").iterdir() if path.is_dir())
    if actual_dirs != sorted(EXPECTED_CELL_IDS):
        raise RuntimeError("supplemental artifact contains a missing or unauthorized cell")
    for cell in cells:
        checkpoint = _reproduce_checkpoint(root, cell, expected_mode)
        if _read(root / "cells" / cell["cell_id"] / "CHECKPOINT.json") != checkpoint:
            raise RuntimeError(f"supplemental checkpoint does not reproduce: {cell['cell_id']}")
        _validate_receipt(root, cell, checkpoint)
    if expected_mode == "fake" and list(root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl")):
        raise RuntimeError("supplemental no-model preflight made an upstream request")
    report = build_report(root)
    report_path = PREFLIGHT_REPORT_PATH if expected_mode == "fake" else REPORT_PATH
    if _read(root / "SUMMARY.json") != report or _read(report_path) != report:
        raise RuntimeError("supplemental report does not reproduce")
    _validate_hashes(root)
    _validate_original_evidence()
    return report


def _finish(root: Path, progress: dict[str, Any], status: str, stop: dict[str, Any] | None = None) -> int:
    progress["status"] = status
    progress["finished_at"] = time.time()
    if stop is not None:
        progress["stop"] = stop
    _write_progress(root, progress)
    _write_report(root)
    _write_hashes(root)
    _validate_original_evidence()
    _log(f"supplemental outcome {status}; checkpoints {len(progress['cells'])}/2")
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
            raise RuntimeError("paid runner identity differs from the finalized no-model preflight")
    with _lock(), _source_bundle() as bundle:
        if (root / "SHA256SUMS.json").is_file():
            try:
                validate(root, expected_mode=mode)
            except RuntimeError:
                pass
            else:
                return 0
        progress = _load_progress(root, mode, identity, bundle)
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
        for index, cell in enumerate(_cells()):
            cell_id = str(cell["cell_id"])
            supplemental_id = str(cell["supplemental_cell_id"])
            try:
                _validate_scope()
                action = _recover(root, progress, cell, mode, ledger)
                if action == "skip":
                    checkpoint = next(item for item in progress["cells"] if item.get("supplemental_cell_id") == supplemental_id)
                    if _policy_refusal(checkpoint):
                        return _finish(
                            root,
                            progress,
                            "policy_refusal",
                            {"cell_id": supplemental_id, "reason": "exact original cyber_policy refusal repeated; never retry"},
                        )
                    continue
                if action == "blocked":
                    return _finish(root, progress, "fail_closed", progress.get("stop"))
                if ledger is not None:
                    ledger.reserve_cell(cell_id)
                    progress["budget"] = ledger.state
                    _write_progress(root, progress)
                _log(f"launching {mode} supplemental cell {supplemental_id}")
                checkpoint = direct_launch._run_cell(
                    root=root,
                    task=str(cell["task"]),
                    harness="thinharness",
                    mode=mode,
                    api_key=credential,
                    bundle=bundle,
                    identity=identity,
                    benchmark_id=BENCHMARK_ID,
                    jobs_dir=jobs_dir,
                    expected_cells=EXPECTED_CELL_IDS,
                    selection_path=SELECTION_PATH,
                    budget_control=ledger,
                )
                checkpoint = _decorate(checkpoint, cell)
                atomic_json(root / "cells" / cell_id / "CHECKPOINT.json", checkpoint)
                refusal = _policy_refusal(checkpoint)
                if refusal:
                    _write_policy_refusal(root, cell, checkpoint)
                _write_receipt(root, cell, checkpoint)
                progress["cells"].append(checkpoint)
                if checkpoint.get("status") == "completed":
                    if ledger is not None:
                        ledger.finish_cell(cell_id)
                        progress["budget"] = ledger.state
                elif ledger is not None:
                    ledger.fail(cell_id, f"cell ended without a complete receipt: {checkpoint.get('status')}")
                    progress["budget"] = ledger.state
                _write_progress(root, progress, checkpoint)
                if refusal:
                    return _finish(
                        root,
                        progress,
                        "policy_refusal",
                        {"cell_id": supplemental_id, "reason": "exact original cyber_policy refusal repeated; never retry"},
                    )
                if checkpoint.get("status") != "completed":
                    return _finish(
                        root,
                        progress,
                        "fail_closed",
                        {"cell_id": supplemental_id, "reason": str(checkpoint.get("status"))},
                    )
                if ledger is not None and ledger.blocked is not None:
                    return _finish(root, progress, "cap_exceeded", ledger.blocked)
                if index == 0:
                    _validate_original_evidence()
            except BaseException as exc:
                marker = root / "cells" / cell_id / "MODEL_REQUEST_STARTED.jsonl"
                if (
                    marker.is_file()
                    and marker.stat().st_size
                    and not any(item.get("supplemental_cell_id") == supplemental_id for item in progress["cells"])
                ):
                    cell_dir = root / "cells" / cell_id
                    checkpoint = _decorate(
                        direct_validate.cell_summary(cell_dir, status="consumed_interrupted", real_model_attempted=True), cell
                    )
                    checkpoint["recovery_validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
                    atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
                    _write_receipt(root, cell, checkpoint)
                    progress["cells"].append(checkpoint)
                    _write_progress(root, progress, checkpoint)
                if ledger is not None:
                    if marker.is_file() and marker.stat().st_size:
                        ledger.fail(cell_id, f"fail closed after consumed request: {exc}")
                    else:
                        ledger.release_pre_request(cell_id, str(exc))
                    progress["budget"] = ledger.state
                return _finish(
                    root,
                    progress,
                    "fail_closed",
                    {"cell_id": supplemental_id, "type": type(exc).__name__, "reason": str(exc)},
                )
        result = _finish(root, progress, "completed")
        validate(root, expected_mode=mode)
        return result


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
        print("supplemental scope, identities, caps, and immutable original evidence passed")
        return 0
    return run(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
