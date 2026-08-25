"""Restart-safe two-cell ThinHarness replicate runner and report validator."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import direct_launch, direct_validate
from .direct_constants import ARTIFACT_DIR as ORIGINAL_ROOT
from .direct_constants import REPOSITORY_ROOT, THINHARNESS_COMMIT
from .source_bundle import ExactCommitBundle, exact_commit_bundle

BENCHMARK_ID = "direct-openai-thinharness-replicates-v1"
CONFIG_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-thinharness-replicates.json"
ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / BENCHMARK_ID
PREFLIGHT_ROOT = REPOSITORY_ROOT / "artifacts" / f"{BENCHMARK_ID}-preflight"
REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}.json"
PREFLIGHT_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}-preflight.json"
RUN_ROOT = REPOSITORY_ROOT / "runs" / BENCHMARK_ID
_LOCK_PATH = RUN_ROOT / "launch.lock"
_IDENTITY_FILES = tuple(
    sorted(
        set(direct_launch._IDENTITY_FILES)
        | {
            "configs/direct-openai-thinharness-replicates.json",
            "scripts/direct-openai-thinharness-replicates-checks.sh",
            "scripts/direct-openai-thinharness-replicates-preflight.sh",
            "scripts/run-direct-openai-thinharness-replicates.sh",
            "tbench/direct_replicates.py",
            "tbench/dna_analysis.py",
        }
    )
)
_ERROR_SIGNATURES = {
    "nginx-request-logging": {
        "test": "test_log_file_format",
        "message": "Status code missing in logs",
        "trace_marker": "status=$status",
        "concrete_error": "The custom log wrote status=<code>; the verifier requires a whitespace-delimited status code.",
    },
    "sanitize-git-repo": {
        "test": "test_correct_replacement_of_secret_information",
        "message": "assert contaminated_text == decontaminated_text",
        "trace_marker": "'https://<your-github-token>@github.com",
        "concrete_error": (
            "The model added literal single quotes around placeholders; "
            "the verifier's exact expected files do not contain them."
        ),
    },
}


def _config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("replicate configuration is not an object")
    return value


def _cells() -> tuple[dict[str, Any], ...]:
    values = _config().get("cells")
    if not isinstance(values, list) or len(values) != 2 or not all(isinstance(item, dict) for item in values):
        raise RuntimeError("replicate configuration must contain exactly two cells")
    return tuple(values)


def _cell_ids() -> tuple[str, ...]:
    return tuple(str(item["cell_id"]) for item in _cells())


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


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_identity() -> dict[str, Any]:
    files: dict[str, str] = {}
    for name in _IDENTITY_FILES:
        path = REPOSITORY_ROOT / name
        if not path.is_file():
            raise RuntimeError(f"replicate runner identity input is absent: {name}")
        files[name] = _sha256(path)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"files": files, "files_sha256": digest}


def _validate_frozen_scope() -> None:
    config = _config()
    cells = _cells()
    expected = ("nginx-request-logging--thinharness", "sanitize-git-repo--thinharness")
    if _cell_ids() != expected:
        raise RuntimeError("replicate scope is not the exact authorized two-cell order")
    allowed_tasks = {"nginx-request-logging", "sanitize-git-repo"}
    if any(item.get("harness") != "thinharness" or item.get("task") not in allowed_tasks for item in cells):
        raise RuntimeError("replicate scope includes a forbidden harness or task")
    execution = config.get("execution") or {}
    retries = execution.get("retries") or {}
    if (
        execution.get("thinharness_version") != "0.7.0"
        or execution.get("thinharness_commit") != THINHARNESS_COMMIT
        or execution.get("model") != "gpt-5.6-sol"
        or execution.get("reasoning") != {"effort": "xhigh", "summary": "auto"}
        or execution.get("text") != {"verbosity": "low"}
        or execution.get("provider_timeout_seconds") != 1800
        or execution.get("attempts_per_cell") != 1
        or execution.get("concurrency") != 1
        or set(retries.values()) != {0}
    ):
        raise RuntimeError("replicate execution settings differ from the frozen original settings")
    original_selection = json.loads((REPOSITORY_ROOT / "configs" / "direct-openai-20task-selection.json").read_text(encoding="utf-8"))
    originals = {item["task"]: item for item in original_selection["selected"]}
    for cell in cells:
        original = originals[cell["task"]]
        for name in (
            "task_package_digest",
            "task_toml_sha256",
            "instruction_sha256",
            "task_tree_sha256",
            "agent_timeout_sec",
            "verifier_timeout_sec",
            "cpus",
            "memory_mb",
            "storage_mb",
            "image",
        ):
            if cell.get(name) != original.get(name):
                raise RuntimeError(f"replicate task identity differs for {cell['task']}: {name}")


def _validate_original_immutable() -> None:
    config = _config()["original_immutability"]
    expected = {
        ORIGINAL_ROOT / "SHA256SUMS.json": config["sha256_manifest_sha256"],
        ORIGINAL_ROOT / "SUMMARY.json": config["summary_sha256"],
        REPOSITORY_ROOT / "reports" / "direct-openai-20task-pairwise.json": config["report_sha256"],
    }
    for path, digest in expected.items():
        if _sha256(path) != digest:
            raise RuntimeError(f"original 20-task evidence changed: {path}")
    direct_validate.validate_hashes(ORIGINAL_ROOT)


@contextmanager
def _lock() -> Iterator[None]:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another replicate launcher holds the exclusive lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _source_bundle() -> Iterator[ExactCommitBundle]:
    raw = os.getenv(direct_launch.LOCAL_SOURCE_ENV)
    if not raw:
        raise RuntimeError(f"{direct_launch.LOCAL_SOURCE_ENV} must name a clean ThinHarness checkout")
    with exact_commit_bundle(Path(raw), THINHARNESS_COMMIT, temporary_prefix=f"{BENCHMARK_ID}-source-") as bundle:
        yield bundle


def _source_identity(bundle: ExactCommitBundle) -> dict[str, Any]:
    return direct_launch._source_identity(bundle)


def _progress_path(root: Path) -> Path:
    return root / "progress.json"


def _write_progress(root: Path, progress: dict[str, Any], event: dict[str, Any] | None = None) -> None:
    progress["updated_at"] = time.time()
    _atomic_json(_progress_path(root), progress)
    if event is not None:
        _append_jsonl(root / "progress.jsonl", event)
    _atomic_json(
        root / "OUTCOME.json",
        {
            "schema_version": 1,
            "benchmark_id": BENCHMARK_ID,
            "label": "new_replicates",
            "mode": progress["mode"],
            "status": progress["status"],
            "checkpointed_cells": len(progress["cells"]),
            "planned_cells": 2,
            "stop": progress.get("stop"),
        },
    )


def _load_or_create_progress(root: Path, mode: str, identity: dict[str, Any], bundle: ExactCommitBundle) -> dict[str, Any]:
    source_identity = _source_identity(bundle)
    path = _progress_path(root)
    if path.is_file():
        progress = json.loads(path.read_text(encoding="utf-8"))
        if progress.get("mode") != mode or progress.get("planned_cells") != list(_cell_ids()):
            raise RuntimeError("existing replicate progress differs from the frozen scope")
        if progress.get("source_identity") != source_identity:
            raise RuntimeError("existing replicate source identity differs")
        if progress.get("runner_identity") != identity and list(root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl")):
            raise RuntimeError("replicate runner identity changed after a model request began")
        progress["runner_identity"] = identity
        progress["status"] = "running"
        progress.pop("finished_at", None)
        progress.pop("stop", None)
        return progress
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONFIG_PATH, root / "settings.json")
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "label": "new_replicates",
        "original_benchmark_id": "direct-openai-20task-pairwise",
        "mode": mode,
        "status": "running",
        "started_at": time.time(),
        "planned_cells": list(_cell_ids()),
        "cells": [],
        "source_bundle_sha256": bundle.sha256,
        "source_identity": source_identity,
        "runner_identity": identity,
    }


def _recover_or_skip(root: Path, progress: dict[str, Any], cell_id: str, mode: str) -> bool:
    done = {item.get("cell_id") for item in progress["cells"]}
    cell_dir = root / "cells" / cell_id
    if cell_id in done:
        checkpoint = json.loads((cell_dir / "CHECKPOINT.json").read_text(encoding="utf-8"))
        if checkpoint.get("cell_id") != cell_id:
            raise RuntimeError(f"replicate checkpoint identity differs: {cell_id}")
        return True
    if not cell_dir.exists():
        return False
    marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
    if mode == "real" and marker.is_file() and marker.stat().st_size:
        checkpoint_path = cell_dir / "CHECKPOINT.json"
        checkpoint = (
            json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint_path.is_file()
            else direct_validate.recover_consumed_cell(cell_dir, mode="real", cell_id=cell_id)
        )
        if checkpoint.get("real_model_attempted") is not True or checkpoint.get("never_rerun") is not True:
            raise RuntimeError(f"consumed replicate checkpoint is invalid: {cell_id}")
        _atomic_json(checkpoint_path, checkpoint)
        progress["cells"].append(checkpoint)
        _write_progress(root, progress, checkpoint)
        return True
    target = root / "infrastructure-attempts" / cell_id / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(cell_dir), target)
    return False


def _trial(cell_dir: Path) -> Path:
    trials = [path for path in (cell_dir / "job").iterdir() if path.is_dir()]
    if len(trials) != 1:
        raise RuntimeError(f"expected one trial in {cell_dir}")
    return trials[0]


def _verifier_stdout(cell_dir: Path) -> str:
    path = _trial(cell_dir) / "verifier" / "test-stdout.txt"
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _tool_trace(cell_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in (cell_dir / "gateway-audit.jsonl").read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        for output in (item.get("response") or {}).get("output") or []:
            if not isinstance(output, dict) or output.get("type") != "function_call":
                continue
            arguments = output.get("arguments")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                parsed = arguments
            records.append({"sequence": item.get("sequence"), "name": output.get("name"), "arguments": parsed})
    return records


def _trace_contains(cell_dir: Path, marker: str) -> bool:
    return marker in json.dumps(_tool_trace(cell_dir), ensure_ascii=False, sort_keys=True)


def _comparison(root: Path, task: str) -> dict[str, Any]:
    root = root.resolve()
    cell_id = f"{task}--thinharness"
    original = ORIGINAL_ROOT / "cells" / cell_id
    replicate = root / "cells" / cell_id
    signature = _ERROR_SIGNATURES[task]
    original_stdout = _verifier_stdout(original)
    replicate_stdout = _verifier_stdout(replicate)
    original_error = signature["test"] in original_stdout and signature["message"] in original_stdout
    replicate_error = signature["test"] in replicate_stdout and signature["message"] in replicate_stdout
    original_marker = _trace_contains(original, signature["trace_marker"])
    replicate_marker = _trace_contains(replicate, signature["trace_marker"])
    return {
        "task": task,
        "original_cell_id": cell_id,
        "replicate_id": f"{cell_id}--replicate-1",
        "concrete_error": signature["concrete_error"],
        "original_error_established": original_error,
        "original_trace_marker_present": original_marker,
        "replicate_error_established": replicate_error,
        "replicate_trace_marker_present": replicate_marker,
        "concrete_error_recurred": original_error and replicate_error,
        "basis": "Exact verifier test/message signature plus preserved model tool-call trace marker.",
        "evidence": {
            "original_gateway_audit": str((original / "gateway-audit.jsonl").relative_to(REPOSITORY_ROOT)),
            "original_verifier_stdout": str((_trial(original) / "verifier" / "test-stdout.txt").relative_to(REPOSITORY_ROOT)),
            "replicate_gateway_audit": str((replicate / "gateway-audit.jsonl").relative_to(REPOSITORY_ROOT)),
            "replicate_verifier_stdout": str((_trial(replicate) / "verifier" / "test-stdout.txt").relative_to(REPOSITORY_ROOT)),
        },
    }


def _aggregate(checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    usage_names = (
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    usage = {name: 0 for name in usage_names}
    costs = 0.0
    rewards: list[float] = []
    requests = 0
    tools = 0
    for checkpoint in checkpoints:
        for name in usage:
            value = (checkpoint.get("usage") or {}).get(name)
            if isinstance(value, int):
                usage[name] += value
        cost = (checkpoint.get("cost") or {}).get("api_equivalent_total")
        if isinstance(cost, int | float):
            costs += float(cost)
        reward = checkpoint.get("reward")
        if isinstance(reward, int | float):
            rewards.append(float(reward))
        requests += int(checkpoint.get("request_count") or 0)
        tools += sum(int(batch.get("tool_calls_in_response") or 0) for batch in checkpoint.get("batching") or [])
    return {
        "usage": usage,
        "api_equivalent_cost_usd": costs,
        "actual_cash_total_usd": None,
        "request_count": requests,
        "tool_count": tools,
        "reward_sum": sum(rewards),
        "reward_count": len(rewards),
    }


def build_report(root: Path) -> dict[str, Any]:
    progress = json.loads(_progress_path(root).read_text(encoding="utf-8"))
    checkpoints = progress.get("cells") or []
    report = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "label": "new_replicates",
        "original_benchmark_id": "direct-openai-20task-pairwise",
        "mode": progress.get("mode"),
        "status": progress.get("status"),
        "planned_cells": 2,
        "checkpointed_cells": len(checkpoints),
        "cells": checkpoints,
        "aggregate": _aggregate(checkpoints),
        "runner_identity": progress.get("runner_identity"),
        "source_identity": progress.get("source_identity"),
        "original_evidence_immutable": True,
        "comparisons": [],
        "reproduce": {
            "report": "uv run python -m tbench.direct_replicates validate artifacts/direct-openai-thinharness-replicates-v1 --check-report",
            "validation": "./scripts/direct-openai-thinharness-replicates-checks.sh",
        },
        "stop": progress.get("stop"),
    }
    if progress.get("mode") == "real" and len(checkpoints) == 2:
        report["comparisons"] = [_comparison(root, task) for task in ("nginx-request-logging", "sanitize-git-repo")]
    return report


def _write_report(root: Path) -> dict[str, Any]:
    report = build_report(root)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (root / "SUMMARY.json").write_text(content, encoding="utf-8")
    target = PREFLIGHT_REPORT_PATH if report["mode"] == "fake" else REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return report


def _write_hashes(root: Path) -> dict[str, str]:
    hashes = {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    _atomic_json(root / "SHA256SUMS.json", hashes)
    return hashes


def _validate_hashes(root: Path) -> None:
    expected = json.loads((root / "SHA256SUMS.json").read_text(encoding="utf-8"))
    actual = {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    if actual != expected:
        raise RuntimeError("replicate artifact SHA256 manifest differs")


def validate(root: Path, *, expected_mode: str, check_report: bool = False) -> dict[str, Any]:
    _validate_frozen_scope()
    _validate_original_immutable()
    progress = json.loads(_progress_path(root).read_text(encoding="utf-8"))
    if progress.get("mode") != expected_mode or progress.get("status") != "completed":
        raise RuntimeError("replicate run is not completed in the expected mode")
    if [item.get("cell_id") for item in progress.get("cells") or []] != list(_cell_ids()):
        raise RuntimeError("replicate checkpoints differ from the exact authorized order")
    actual_cell_dirs = sorted(path.name for path in (root / "cells").iterdir() if path.is_dir())
    if actual_cell_dirs != sorted(_cell_ids()):
        raise RuntimeError("replicate artifact contains an unauthorized cell directory")
    for cell_id in _cell_ids():
        direct_validate.validate_cell(root / "cells" / cell_id, mode=expected_mode, cell_id=cell_id)
    _validate_hashes(root)
    report = build_report(root)
    recorded = (root / "SUMMARY.json").read_text(encoding="utf-8")
    reproduced = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if recorded != reproduced:
        raise RuntimeError("replicate SUMMARY.json is not reproducible from immutable evidence")
    target = PREFLIGHT_REPORT_PATH if expected_mode == "fake" else REPORT_PATH
    if target.read_text(encoding="utf-8") != reproduced:
        raise RuntimeError("replicate report copy differs from reproduced evidence")
    if expected_mode == "fake":
        if any(item.get("reward") != 0 or item.get("real_model_attempted") for item in progress["cells"]):
            raise RuntimeError("replicate no-model preflight made a real attempt or got a nonzero reward")
    elif len(report["comparisons"]) != 2:
        raise RuntimeError("replicate report lacks both original comparisons")
    if check_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return report


def _finish(root: Path, progress: dict[str, Any], status: str, stop: dict[str, Any] | None = None) -> int:
    progress["status"] = status
    progress["finished_at"] = time.time()
    if stop is not None:
        progress["stop"] = stop
    _write_progress(root, progress)
    _write_report(root)
    _write_hashes(root)
    _validate_original_immutable()
    return 0 if status == "completed" else 2


def run(command: str) -> int:
    if command not in {"preflight", "run"}:
        raise ValueError("command must be preflight or run")
    mode = "fake" if command == "preflight" else "real"
    root = PREFLIGHT_ROOT if mode == "fake" else ARTIFACT_ROOT
    _validate_frozen_scope()
    _validate_original_immutable()
    credential = direct_launch._validate_environment(mode)
    if mode == "real":
        validate(PREFLIGHT_ROOT, expected_mode="fake")
    identity = _repository_identity()
    with _lock(), _source_bundle() as bundle:
        if (root / "SHA256SUMS.json").is_file():
            try:
                validate(root, expected_mode=mode)
            except RuntimeError:
                pass
            else:
                return 0
        progress = _load_or_create_progress(root, mode, identity, bundle)
        _write_progress(root, progress)
        try:
            for cell in _cells():
                cell_id = str(cell["cell_id"])
                if _recover_or_skip(root, progress, cell_id, mode):
                    if progress["cells"][-1].get("status") == "credit_exhausted":
                        return _finish(root, progress, "credit_exhausted", {"cell_id": cell_id})
                    continue
                checkpoint = direct_launch._run_cell(
                    root=root,
                    task=str(cell["task"]),
                    harness="thinharness",
                    mode=mode,
                    api_key=credential,
                    bundle=bundle,
                    identity=identity,
                )
                checkpoint["replicate_id"] = cell["replicate_id"]
                checkpoint["original_cell_id"] = cell["original_cell_id"]
                _atomic_json(root / "cells" / cell_id / "CHECKPOINT.json", checkpoint)
                progress["cells"].append(checkpoint)
                _write_progress(root, progress, checkpoint)
                if checkpoint["status"] == "credit_exhausted":
                    return _finish(root, progress, "credit_exhausted", {"cell_id": cell_id})
                if checkpoint["status"] == "infrastructure_blocker":
                    return _finish(root, progress, "external_blocker", {"cell_id": cell_id})
        except BaseException as exc:
            progress["status"] = "external_blocker"
            progress["stop"] = {"type": type(exc).__name__, "message": str(exc)}
            progress["finished_at"] = time.time()
            _write_progress(root, progress)
            raise
        result = _finish(root, progress, "completed")
        validate(root, expected_mode=mode)
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    subparsers.add_parser("run")
    validation = subparsers.add_parser("validate")
    validation.add_argument("root", type=Path)
    validation.add_argument("--mode", choices=("fake", "real"), default="real")
    validation.add_argument("--check-report", action="store_true")
    args = parser.parse_args()
    if args.command == "validate":
        validate(args.root, expected_mode=args.mode, check_report=args.check_report)
        return 0
    return run(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
