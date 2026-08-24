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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    ATTEMPTS,
    CAMPAIGN_ID,
    CONCURRENCY,
    DATASET_DIGEST,
    DATASET_NAME,
    HARBOR_RETRIES,
    IMPLEMENTATION_BUDGET_USD,
    LEGACY_IMPLEMENTATION_SPEND_USD,
    LEGACY_THINHARNESS_COMMIT,
    MODEL_REF,
    REPOSITORY_ROOT,
    TASK_NAME,
    THINHARNESS_COMMIT,
)
from .source_bundle import exact_commit_bundle

JOBS_DIR = REPOSITORY_ROOT / "jobs"
RUNS_DIR = REPOSITORY_ROOT / "runs"
IMPLEMENTATION_STATE = RUNS_DIR / "implementation-budget.json"
PAID_LAUNCH_LOCK = RUNS_DIR / "paid-launch.lock"
CURRENT_PAID_ARTIFACTS = REPOSITORY_ROOT / "artifacts" / f"paid-e2e-{CAMPAIGN_ID}"
LOCAL_SOURCE_ENV = "TB_THINHARNESS_LOCAL_SOURCE"


@dataclass(frozen=True)
class SourceOverride:
    """One transient exact-commit bundle staged for an unpushed candidate."""

    mode: str
    bundle_path: Path | None = None
    bundle_sha256: str | None = None


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


def harbor_command(
    *,
    mode: str,
    job_name: str,
    launch_id: str,
    prior_spend: float,
    source_override: SourceOverride | None = None,
) -> list[str]:
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
    if source_override is not None and source_override.bundle_path is not None:
        command.extend(
            [
                "--agent-kwarg",
                f"source_bundle_path={source_override.bundle_path}",
                "--agent-kwarg",
                f"source_bundle_sha256={source_override.bundle_sha256}",
            ]
        )
    return command


def _new_launch(mode: str) -> tuple[str, str]:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    short = uuid.uuid4().hex[:8]
    launch_id = f"{mode}-{stamp}-{short}"
    return launch_id, f"native-thinharness-{mode}-{CAMPAIGN_ID}-regex-log-{stamp}-{short}"


def _load_legacy_paid_spend() -> float:
    report_path = REPOSITORY_ROOT / "reports" / "implementation-e2e.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("reward") != 1.0:
        raise RuntimeError("legacy paid evidence did not pass its verifier")
    if report.get("identity", {}).get("thinharness_commit") != LEGACY_THINHARNESS_COMMIT:
        raise RuntimeError("legacy paid evidence has an unexpected ThinHarness commit")
    spend = report.get("api_equivalent_cost_usd")
    if spend != LEGACY_IMPLEMENTATION_SPEND_USD:
        raise RuntimeError("legacy paid evidence has an unexpected corrected spend")
    return float(spend)


def _load_current_paid_result() -> tuple[dict[str, Any] | None, float]:
    if not CURRENT_PAID_ARTIFACTS.is_dir():
        return None, 0.0
    from .validate import ValidationError, validate_paid_artifacts

    try:
        result = validate_paid_artifacts(
            CURRENT_PAID_ARTIFACTS,
            expected_thinharness_commit=THINHARNESS_COMMIT,
            legacy_underpriced_ledger=False,
        )
    except ValidationError as exc:
        raise RuntimeError(f"current paid receipts are invalid; refusing launch: {exc}") from exc
    spend = result.get("api_equivalent_cost_usd")
    if isinstance(spend, bool) or not isinstance(spend, int | float) or spend < 0:
        raise RuntimeError("current paid spend is invalid")
    return result, float(spend)


def _load_prior_state() -> tuple[dict[str, Any] | None, float]:
    legacy_spend = _load_legacy_paid_spend()
    current, _ = _load_current_paid_result()
    if current is not None and current.get("reward") == 1.0:
        raise RuntimeError("the current candidate task already passed its verifier; refusing another paid launch")
    if not IMPLEMENTATION_STATE.exists():
        return None, legacy_spend
    state = json.loads(IMPLEMENTATION_STATE.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise RuntimeError("implementation budget state is invalid")
    if state.get("thinharness_commit") != THINHARNESS_COMMIT:
        return state, legacy_spend
    if state.get("status") == "launched":
        raise RuntimeError("the current candidate paid launch has no settled receipt; refusing another launch")
    if state.get("status") == "completed":
        raise RuntimeError("the current candidate already used its one authorized paid attempt")
    raise RuntimeError("current candidate implementation budget state is invalid")


@contextmanager
def _transient_source_override() -> Iterator[SourceOverride]:
    """Create a self-cleaning exact-pin bundle only when explicitly requested."""
    raw_source = os.getenv(LOCAL_SOURCE_ENV)
    if not raw_source:
        yield SourceOverride(mode="canonical-github")
        return
    with exact_commit_bundle(
        Path(raw_source), THINHARNESS_COMMIT, temporary_prefix=f"tbench-{CAMPAIGN_ID}-bundle-"
    ) as bundle:
        yield SourceOverride(
            mode="local-git-bundle-override",
            bundle_path=bundle.path,
            bundle_sha256=bundle.sha256,
        )


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
    with _transient_source_override() as source_override:
        if mode == "paid":
            with _exclusive_paid_launch():
                return _run_unlocked(mode, source_override=source_override)
        return _run_unlocked(mode, source_override=source_override)


def _run_unlocked(mode: str, *, source_override: SourceOverride | None = None) -> int:
    """Execute after the caller applies the source and paid-launch controls."""
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
                "thinharness_commit": THINHARNESS_COMMIT,
            },
        )
    command = harbor_command(
        mode=mode,
        job_name=job_name,
        launch_id=launch_id,
        prior_spend=prior_spend,
        source_override=source_override,
    )
    repository_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    launch_receipt = {
        "schema_version": 2,
        "mode": mode,
        "launch_id": launch_id,
        "job_name": job_name,
        "command": command,
        "credential_source": "process environment" if mode == "paid" else None,
        "thinharness_commit": THINHARNESS_COMMIT,
        "reproduction_repository_commit": repository_commit,
        "source": {
            "mode": source_override.mode if source_override is not None else "canonical-github",
            "canonical_repository": "https://github.com/ryanbbrown/thinharness.git",
            "transient_bundle_sha256": source_override.bundle_sha256 if source_override is not None else None,
            "transient_bundle_committed": False,
        },
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
                    "prior_implementation_spend_usd": prior_spend,
                    "thinharness_commit": THINHARNESS_COMMIT,
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
