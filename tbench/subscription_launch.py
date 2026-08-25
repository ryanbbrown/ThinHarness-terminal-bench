"""Sequential Harbor launcher for the matched Codex-subscription smoke."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
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

from . import subscription_validate
from .source_bundle import ExactCommitBundle, exact_commit_bundle
from .subscription_constants import (
    ATTEMPTS,
    CODEX_AUTH_PATH,
    CONCURRENCY,
    DATASET_DIGEST,
    DATASET_NAME,
    EXPECTED_CELLS,
    GATEWAY_TOKEN_ENV,
    GATEWAY_URL_ENV,
    LOCAL_SOURCE_ENV,
    MODEL,
    REPOSITORY_ROOT,
    RETRIES,
    SELECTION_PATH,
    SMOKE_ID,
    SOURCE_BUNDLE_ENV,
    SOURCE_BUNDLE_SHA_ENV,
    SUBSCRIPTION_ARTIFACT_DIR,
    SUBSCRIPTION_JOBS_DIR,
    SUBSCRIPTION_RUNS_DIR,
    TASKS,
    THINHARNESS_COMMIT,
)
from .subscription_gateway import GatewayIdentity, run_gateway

_LOCK = SUBSCRIPTION_RUNS_DIR / "launch.lock"
_PREFLIGHT_DIR = REPOSITORY_ROOT / "artifacts" / f"{SMOKE_ID}-preflight"
_IDENTITY_FILES = (
    "configs/container-runtime-requirements.txt",
    "configs/pi-subscription-package-lock.json",
    "configs/pi-subscription-package.json",
    "configs/subscription-extension-selection.json",
    "prompts/pi-0.84.2-system-prompt.md",
    "pyproject.toml",
    "scripts/install-subscription-pi.sh",
    "scripts/install-subscription-thinharness.sh",
    "tbench/container_security.py",
    "tbench/pi_subscription_probe.mjs",
    "tbench/source_bundle.py",
    "tbench/subscription_agent.py",
    "tbench/subscription_constants.py",
    "tbench/subscription_container.py",
    "tbench/subscription_gateway.py",
    "tbench/subscription_launch.py",
    "tbench/subscription_validate.py",
    "uv.lock",
)


def _repository_identity() -> dict[str, Any]:
    files = {}
    for name in _IDENTITY_FILES:
        path = REPOSITORY_ROOT / name
        if not path.is_file():
            raise RuntimeError(f"runner identity input is absent: {name}")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"git_head": head, "files": files, "files_sha256": digest}


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


@contextmanager
def _lock() -> Iterator[None]:
    SUBSCRIPTION_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another subscription smoke launcher holds the exclusive lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def _source_bundle() -> Iterator[ExactCommitBundle]:
    raw = os.getenv(LOCAL_SOURCE_ENV)
    if not raw:
        raise RuntimeError(f"{LOCAL_SOURCE_ENV} must name a clean canonical ThinHarness checkout containing the pin")
    with exact_commit_bundle(
        Path(raw), THINHARNESS_COMMIT, temporary_prefix=f"{SMOKE_ID}-source-"
    ) as bundle:
        yield bundle


def preview_source_bundle() -> dict[str, Any]:
    """Verify the exact bundle path without starting Harbor, a gateway, or cproxy."""
    with _source_bundle() as bundle:
        return {
            "schema_version": 1,
            "upstream_requests": 0,
            "target_commit": bundle.target_commit,
            "source_head": bundle.source_head,
            "source_head_excluded": bundle.source_head_excluded,
            "advertised_heads": [[bundle.target_commit, bundle.advertised_ref]],
            "bundle_sha256": bundle.sha256,
            "bundle_persisted": False,
        }


def _harbor_command(*, cell_id: str, task: str, harness: str, mode: str, job_name: str) -> list[str]:
    harbor = shutil.which("harbor")
    if not harbor:
        raise RuntimeError("harbor is not installed; run through uv")
    return [
        harbor,
        "run",
        "--dataset",
        f"{DATASET_NAME}@{DATASET_DIGEST}",
        "--agent",
        "tbench.subscription_agent:SubscriptionSmokeAgent",
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
        str(SUBSCRIPTION_JOBS_DIR),
        "--agent-include-logs",
        "*",
        "--agent-kwarg",
        f"harness={harness}",
        "--agent-kwarg",
        f"cell_id={cell_id}",
        "--agent-kwarg",
        f"mode={mode}",
    ]


def _job_name(cell_id: str, mode: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{SMOKE_ID}-{mode}-{cell_id}-{stamp}-{uuid.uuid4().hex[:8]}"


def _one_trial(job_dir: Path) -> Path:
    trials = [path for path in job_dir.iterdir() if path.is_dir()]
    if len(trials) != 1:
        raise RuntimeError(f"expected one trial in {job_dir}, found {len(trials)}")
    return trials[0]


def _archive(job_dir: Path, *, cell_id: str, mode: str, gateway_dir: Path, launch_path: Path) -> Path:
    root = _PREFLIGHT_DIR if mode == "fake" else SUBSCRIPTION_ARTIFACT_DIR
    target = root / "cells" / cell_id
    if target.exists():
        raise RuntimeError(f"refusing to replace durable cell evidence: {target}")
    target.mkdir(parents=True)
    if job_dir.is_dir():
        shutil.copytree(job_dir, target / "job")
    for name in ("gateway-audit.jsonl", "gateway-identity.json"):
        source = gateway_dir / name
        if source.is_file():
            shutil.copy2(source, target / name)
    shutil.copy2(launch_path, target / "launch.json")
    return target


def _is_preserved_real_cell(path: Path) -> bool:
    launch = path / "launch.json"
    try:
        mode = json.loads(launch.read_text(encoding="utf-8")).get("mode")
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return True
    return mode != "fake"


def _validate_fresh_task_evidence() -> None:
    conflicts = []
    artifact_cell_roots = list((REPOSITORY_ROOT / "artifacts").glob("*/cells"))
    for task in TASKS:
        for cells in artifact_cell_roots:
            conflicts.extend(path for path in sorted(cells.glob(f"{task}--*")) if _is_preserved_real_cell(path))
        conflicts.extend(sorted((REPOSITORY_ROOT / "jobs").glob(f"*/*-real-{task}--*")))
    if conflicts:
        names = ", ".join(str(path.relative_to(REPOSITORY_ROOT)) for path in conflicts)
        raise RuntimeError(f"selected recovery task has preserved prior real-cell evidence: {names}")


def _validate_preflight_gate(root: Path = _PREFLIGHT_DIR) -> None:
    if not (root / "SUMMARY.json").is_file() or not (root / "SHA256SUMS.json").is_file():
        raise RuntimeError("complete finalized preflight evidence is absent")
    result = subscription_validate.validate_artifacts(root, mode="fake")
    subscription_validate.validate_hashes(root)
    if result.get("passed") is not True or len(result.get("cells") or []) != len(EXPECTED_CELLS):
        raise RuntimeError("preflight evidence does not prove all six controlled cells")


def _validate_environment(mode: str) -> None:
    forbidden = [name for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY") if os.getenv(name)]
    if forbidden:
        raise RuntimeError(f"API credential environment is forbidden for subscription smoke: {', '.join(forbidden)}")
    if mode == "real":
        status = subprocess.run(["codex", "login", "status"], check=False, capture_output=True, text=True)
        if status.returncode != 0 or "Logged in using ChatGPT" not in status.stdout + status.stderr:
            raise RuntimeError("Codex CLI is not logged in with the ChatGPT subscription")
        if not CODEX_AUTH_PATH.is_file():
            raise RuntimeError("Codex CLI auth file is absent")


def _run_cell(
    *,
    cell_id: str,
    task: str,
    harness: str,
    mode: str,
    bundle: Path,
    bundle_sha256: str,
) -> dict[str, Any]:
    job_name = _job_name(cell_id, mode)
    job_dir = SUBSCRIPTION_JOBS_DIR / job_name
    gateway_dir = SUBSCRIPTION_RUNS_DIR / f"{mode}-{cell_id}-{uuid.uuid4().hex[:8]}"
    audit_path = gateway_dir / "gateway-audit.jsonl"
    identity_path = gateway_dir / "gateway-identity.json"
    launch_path = gateway_dir / "launch.json"
    with run_gateway(
        cell_id=cell_id,
        mode=mode,
        audit_path=audit_path,
        identity_path=identity_path,
        auth_path=CODEX_AUTH_PATH,
    ) as gateway:
        command = _harbor_command(cell_id=cell_id, task=task, harness=harness, mode=mode, job_name=job_name)
        launch = {
            "schema_version": 1,
            "cell_id": cell_id,
            "task": task,
            "harness": harness,
            "mode": mode,
            "command": command,
            "gateway": _public_gateway_identity(gateway),
            "source_bundle_sha256": bundle_sha256 if harness == "thinharness" else None,
            "runner_identity": _repository_identity(),
            "credentials": "host Codex CLI OAuth read only by cproxy gateway" if mode == "real" else "none; controlled fake",
            "direct_openai": False,
            "retries": {"gateway": 0, "provider": 0, "agent": 0, "harbor": 0},
        }
        _atomic_json(launch_path, launch)
        environment = os.environ.copy()
        for name in list(environment):
            if name.endswith("_API_KEY") or name in {"ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"}:
                environment.pop(name, None)
        environment.update(
            {
                GATEWAY_URL_ENV: gateway.base_url,
                GATEWAY_TOKEN_ENV: gateway.token,
                SOURCE_BUNDLE_ENV: str(bundle),
                SOURCE_BUNDLE_SHA_ENV: bundle_sha256,
            }
        )
        completed = subprocess.run(command, cwd=REPOSITORY_ROOT, env=environment, check=False)
    target = _archive(job_dir, cell_id=cell_id, mode=mode, gateway_dir=gateway_dir, launch_path=launch_path)
    if completed.returncode != 0:
        raise RuntimeError(f"Harbor cell {cell_id} failed with exit {completed.returncode}; evidence preserved at {target}")
    if not audit_path.is_file() or not audit_path.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"gateway audit is empty for {cell_id}; evidence preserved at {target}")
    subscription_validate.validate_cell(target, mode=mode, cell_id=cell_id)
    trial = _one_trial(job_dir)
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    return {
        "cell_id": cell_id,
        "task": task,
        "harness": harness,
        "mode": mode,
        "job": str(job_dir.relative_to(REPOSITORY_ROOT)),
        "trial": trial.name,
        "artifact": str(target.relative_to(REPOSITORY_ROOT)),
        "reward": (result.get("verifier_result") or {}).get("rewards", {}).get("reward"),
        "exception": result.get("exception_info"),
        "harbor_exit_code": completed.returncode,
    }


def _record_real_backend_preflight(root: Path) -> None:
    """Validate host Codex OAuth through cproxy without an upstream request."""
    audit = root / "codex-backend-preflight-audit.jsonl"
    identity = root / "codex-backend-preflight.json"
    with run_gateway(
        cell_id="backend-preflight-no-model-call",
        mode="real",
        audit_path=audit,
        identity_path=identity,
        auth_path=CODEX_AUTH_PATH,
    ):
        pass
    if audit.exists():
        raise RuntimeError("backend preflight unexpectedly made a subscription request")
    value = json.loads(identity.read_text(encoding="utf-8"))
    value["subscription_requests"] = 0
    value["upstream_network_requests"] = 0
    _atomic_json(identity, value)


def _public_gateway_identity(gateway: GatewayIdentity) -> dict[str, Any]:
    return {
        "base_url": gateway.base_url,
        "port": gateway.port,
        "cell_id": gateway.cell_id,
        "mode": gateway.mode,
        "cproxy_version": gateway.cproxy_version,
        "cproxy_commit": gateway.cproxy_commit,
        "upstream": gateway.upstream,
        "ephemeral_token_persisted": False,
    }


def run(mode: str) -> int:
    """Run six controlled preflight cells or the six real matched cells."""
    if mode not in {"preflight", "run"}:
        raise ValueError("mode must be preflight or run")
    gateway_mode = "fake" if mode == "preflight" else "real"
    _validate_environment(gateway_mode)
    _validate_fresh_task_evidence()
    if gateway_mode == "real":
        _validate_preflight_gate()
    artifact_root = _PREFLIGHT_DIR if gateway_mode == "fake" else SUBSCRIPTION_ARTIFACT_DIR
    if artifact_root.exists():
        raise RuntimeError(f"refusing to replace existing smoke evidence: {artifact_root}")
    cells = tuple(
        (cell_id, task, harness)
        for task in TASKS
        for harness in ("pi", "thinharness")
        for cell_id in (f"{task}--{harness}",)
    )
    if tuple(cell_id for cell_id, _, _ in cells) != EXPECTED_CELLS:
        raise RuntimeError("planned cell order differs from the frozen six-cell design")
    state_path = SUBSCRIPTION_RUNS_DIR / f"{mode}-state.json"
    with _lock(), _source_bundle() as source_bundle:
        bundle = source_bundle.path
        bundle_sha256 = source_bundle.sha256
        state: dict[str, Any] = {
            "schema_version": 1,
            "status": "running",
            "mode": mode,
            "gateway_mode": gateway_mode,
            "started_at": time.time(),
            "dataset": f"{DATASET_NAME}@{DATASET_DIGEST}",
            "model": MODEL,
            "cells": [],
            "source_bundle_sha256": bundle_sha256,
            "source_bundle_committed": False,
            "runner_identity": _repository_identity(),
        }
        _atomic_json(state_path, state)
        artifact_root.mkdir(parents=True)
        shutil.copy2(state_path, artifact_root / "run-state.json")
        shutil.copy2(SELECTION_PATH, artifact_root / "selection.json")
        try:
            for cell_id, task, harness in cells:
                result = _run_cell(
                    cell_id=cell_id,
                    task=task,
                    harness=harness,
                    mode=gateway_mode,
                    bundle=bundle,
                    bundle_sha256=bundle_sha256,
                )
                state["cells"].append(result)
                _atomic_json(state_path, state)
                shutil.copy2(state_path, artifact_root / "run-state.json")
        except BaseException as exc:
            state["status"] = "stopped"
            state["error"] = {"type": type(exc).__name__, "message": str(exc)}
            state["finished_at"] = time.time()
            _atomic_json(state_path, state)
            shutil.copy2(state_path, artifact_root / "run-state.json")
            raise
        state["status"] = "completed"
        state["finished_at"] = time.time()
        _atomic_json(state_path, state)
        shutil.copy2(state_path, artifact_root / "run-state.json")
    if mode == "preflight":
        _record_real_backend_preflight(artifact_root)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("bundle-preview", "preflight", "run"))
    args = parser.parse_args()
    if args.mode == "bundle-preview":
        print(json.dumps(preview_source_bundle(), indent=2, sort_keys=True))
        return 0
    return run(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
