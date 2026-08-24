"""Fail-closed Harbor launch commands for preflight and one paid task."""

from __future__ import annotations

import argparse
import fcntl
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

from .constants import (
    ATTEMPTS,
    CONCURRENCY,
    DATASET_DIGEST,
    DATASET_NAME,
    HARBOR_RETRIES,
    IMPLEMENTATION_BUDGET_USD,
    MODEL_REF,
    REPOSITORY_ROOT,
    TASK_NAME,
)

JOBS_DIR = REPOSITORY_ROOT / "jobs"
RUNS_DIR = REPOSITORY_ROOT / "runs"
IMPLEMENTATION_STATE = RUNS_DIR / "implementation-budget.json"
PAID_LAUNCH_LOCK = RUNS_DIR / "paid-launch.lock"
COMMITTED_PAID_ARTIFACTS = REPOSITORY_ROOT / "artifacts" / "paid-e2e"


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


def harbor_command(*, mode: str, job_name: str, launch_id: str, prior_spend: float) -> list[str]:
    """Return the exact single-task, single-attempt Harbor invocation."""
    harbor = shutil.which("harbor")
    if not harbor:
        raise RuntimeError("harbor is not installed; run through `uv run`")
    command = [
        harbor,
        "run",
        "--dataset",
        f"{DATASET_NAME}@{DATASET_DIGEST}",
        "--agent",
        "tbench.agent:NativeThinHarnessAgent",
        "--model",
        MODEL_REF,
        "--env",
        "docker",
        "--include-task-name",
        TASK_NAME,
        "--n-attempts",
        str(ATTEMPTS),
        "--n-concurrent",
        str(CONCURRENCY),
        "--n-concurrent-agents",
        str(CONCURRENCY),
        "--max-retries",
        str(HARBOR_RETRIES),
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
        str(JOBS_DIR),
        "--agent-include-logs",
        "*.json",
        "--agent-kwarg",
        f"preflight_only={'true' if mode == 'preflight' else 'false'}",
        "--agent-kwarg",
        f"launch_id={launch_id}",
        "--agent-kwarg",
        f"prior_implementation_spend_usd={prior_spend}",
    ]
    return command


def _new_launch(mode: str) -> tuple[str, str]:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    short = uuid.uuid4().hex[:8]
    launch_id = f"{mode}-{stamp}-{short}"
    return launch_id, f"native-thinharness-{mode}-regex-log-{stamp}-{short}"


def _load_committed_paid_result() -> tuple[dict[str, Any] | None, float]:
    if not COMMITTED_PAID_ARTIFACTS.is_dir():
        return None, 0.0
    from .validate import ValidationError, validate_paid_artifacts

    try:
        result = validate_paid_artifacts(COMMITTED_PAID_ARTIFACTS)
    except ValidationError as exc:
        raise RuntimeError(f"committed paid receipts are invalid; refusing launch: {exc}") from exc
    spend = result.get("api_equivalent_cost_usd")
    if isinstance(spend, bool) or not isinstance(spend, int | float) or spend < 0:
        raise RuntimeError("committed paid spend is invalid")
    return result, float(spend)


def _load_prior_state() -> tuple[dict[str, Any] | None, float]:
    committed, committed_spend = _load_committed_paid_result()
    if committed is not None and committed.get("reward") == 1.0:
        raise RuntimeError("the committed implementation task already passed its verifier; refusing another paid launch")
    if not IMPLEMENTATION_STATE.exists():
        return None, committed_spend
    state = json.loads(IMPLEMENTATION_STATE.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise RuntimeError("implementation budget state is invalid")
    if state.get("status") == "launched":
        raise RuntimeError("a prior paid launch has no settled receipt; refusing another launch")
    spent = state.get("implementation_spend_usd")
    if isinstance(spent, bool) or not isinstance(spent, int | float) or spent < 0:
        raise RuntimeError("implementation budget state has invalid spend")
    if spent >= IMPLEMENTATION_BUDGET_USD:
        raise RuntimeError("implementation budget is exhausted")
    return state, max(float(spent), committed_spend)


@contextmanager
def _exclusive_paid_launch(path: Path = PAID_LAUNCH_LOCK) -> Iterator[None]:
    """Hold one non-blocking advisory lock for the complete paid Harbor process."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another paid implementation launch holds the exclusive launch lock") from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _find_one(job_dir: Path, name: str) -> Path:
    paths = list(job_dir.glob(f"**/agent/{name}"))
    if len(paths) != 1:
        raise RuntimeError(f"expected one {name} receipt, found {len(paths)}")
    return paths[0]


def run(mode: str) -> int:
    """Run one Harbor preflight or one exclusively locked paid task."""
    if mode not in {"preflight", "paid"}:
        raise ValueError("mode must be preflight or paid")
    if mode == "paid":
        with _exclusive_paid_launch():
            return _run_unlocked(mode)
    return _run_unlocked(mode)


def _run_unlocked(mode: str) -> int:
    """Execute after the caller applies the paid launch lock."""
    launch_id, job_name = _new_launch(mode)
    prior_spend = 0.0
    if mode == "paid":
        _, prior_spend = _load_prior_state()
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not present in the process environment")
        _atomic_json(
            IMPLEMENTATION_STATE,
            {
                "schema_version": 1,
                "status": "launched",
                "launch_id": launch_id,
                "prior_implementation_spend_usd": prior_spend,
                "implementation_ceiling_usd": IMPLEMENTATION_BUDGET_USD,
            },
        )
    command = harbor_command(mode=mode, job_name=job_name, launch_id=launch_id, prior_spend=prior_spend)
    launch_receipt = {
        "schema_version": 1,
        "mode": mode,
        "launch_id": launch_id,
        "job_name": job_name,
        "command": command,
        "credential_source": "process environment" if mode == "paid" else None,
        "wrapper_retries": 0,
    }
    _atomic_json(RUNS_DIR / f"{launch_id}.json", launch_receipt)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    job_dir = JOBS_DIR / job_name
    if mode == "paid":
        try:
            ledger_path = _find_one(job_dir, "api-budget.json")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            if ledger.get("in_flight_request_id") is not None or ledger.get("status") != "completed":
                raise RuntimeError("paid ledger did not settle and finalize")
            current_spend = ledger.get("spent_usd")
            if isinstance(current_spend, bool) or not isinstance(current_spend, int | float):
                raise RuntimeError("paid ledger spend is invalid")
            total = prior_spend + float(current_spend)
            if total > IMPLEMENTATION_BUDGET_USD + 1e-9:
                raise RuntimeError("paid ledger exceeds the implementation cap")
            _atomic_json(
                IMPLEMENTATION_STATE,
                {
                    "schema_version": 1,
                    "status": "completed",
                    "launch_id": launch_id,
                    "implementation_spend_usd": total,
                    "latest_attempt_spend_usd": current_spend,
                    "ledger": str(ledger_path.relative_to(REPOSITORY_ROOT)),
                    "job": str(job_dir.relative_to(REPOSITORY_ROOT)),
                    "harbor_exit_code": completed.returncode,
                },
            )
        except Exception:
            # Keep the pre-launch state as `launched`; the next attempt must fail closed.
            raise
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "paid"))
    args = parser.parse_args()
    return run(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
