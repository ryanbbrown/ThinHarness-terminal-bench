from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tbench.constants import DATASET_DIGEST, LEGACY_IMPLEMENTATION_SPEND_USD, MODEL_REF, TASK_NAME, THINHARNESS_COMMIT
from tbench.launch import (
    SourceOverride,
    _exclusive_paid_launch,
    _load_prior_state,
    _transient_source_override,
    harbor_command,
)


def _value(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def test_harbor_command_is_one_task_one_attempt_zero_retry(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/harbor")

    command = harbor_command(mode="paid", job_name="job", launch_id="launch", prior_spend=0.25)

    assert _value(command, "--dataset").endswith("@" + DATASET_DIGEST)
    assert _value(command, "--include-task-name") == TASK_NAME
    assert _value(command, "--model") == MODEL_REF
    assert _value(command, "--n-attempts") == "1"
    assert _value(command, "--n-concurrent") == "1"
    assert _value(command, "--n-concurrent-agents") == "1"
    assert _value(command, "--max-retries") == "0"
    assert "--no-force-build" in command
    assert "--delete" in command
    assert "--upload" not in command
    assert "--public" not in command
    assert "OPENAI_API_KEY" not in " ".join(command)
    kwargs = [command[index + 1] for index, item in enumerate(command) if item == "--agent-kwarg"]
    assert kwargs == [
        "preflight_only=false",
        "launch_id=launch",
        "prior_implementation_spend_usd=0.25",
    ]


def test_harbor_command_stages_explicit_transient_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/harbor")
    bundle = tmp_path / "source.bundle"
    bundle.write_bytes(b"bundle")
    source = SourceOverride("local-git-bundle-override", bundle, hashlib.sha256(b"bundle").hexdigest())

    command = harbor_command(mode="preflight", job_name="job", launch_id="launch", prior_spend=0, source_override=source)

    kwargs = [command[index + 1] for index, item in enumerate(command) if item == "--agent-kwarg"]
    assert kwargs[-2:] == [f"source_bundle_path={bundle}", f"source_bundle_sha256={source.bundle_sha256}"]
    bundle.unlink()


def test_unsettled_current_candidate_launch_fails_closed(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "implementation-budget.json"
    state.write_text(json.dumps({"status": "launched", "thinharness_commit": THINHARNESS_COMMIT}))
    monkeypatch.setattr("tbench.launch.IMPLEMENTATION_STATE", state)
    monkeypatch.setattr("tbench.launch.CURRENT_PAID_ARTIFACTS", tmp_path / "absent")

    with pytest.raises(RuntimeError, match="current candidate paid launch has no settled receipt"):
        _load_prior_state()


def test_completed_current_candidate_launch_refuses_duplicate(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "implementation-budget.json"
    state.write_text(json.dumps({"status": "completed", "thinharness_commit": THINHARNESS_COMMIT}))
    monkeypatch.setattr("tbench.launch.IMPLEMENTATION_STATE", state)
    monkeypatch.setattr("tbench.launch.CURRENT_PAID_ARTIFACTS", tmp_path / "absent")

    with pytest.raises(RuntimeError, match="one authorized paid attempt"):
        _load_prior_state()


def test_legacy_runtime_state_seeds_corrected_cumulative_spend(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "implementation-budget.json"
    state.write_text(json.dumps({"status": "completed", "implementation_spend_usd": 0.096848}))
    monkeypatch.setattr("tbench.launch.IMPLEMENTATION_STATE", state)
    monkeypatch.setattr("tbench.launch.CURRENT_PAID_ARTIFACTS", tmp_path / "absent")

    _, spend = _load_prior_state()

    assert spend == pytest.approx(LEGACY_IMPLEMENTATION_SPEND_USD)


def test_concurrent_paid_launch_is_excluded(tmp_path: Path) -> None:
    lock = tmp_path / "paid.lock"

    with _exclusive_paid_launch(lock):
        with pytest.raises(RuntimeError, match="exclusive launch lock"):
            with _exclusive_paid_launch(lock):
                pass


def test_transient_local_source_bundle_is_exact_and_self_cleaning(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
    (source / "file").write_text("content")
    subprocess.run(["git", "-C", str(source), "add", "file"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.setenv("TB_THINHARNESS_LOCAL_SOURCE", str(source))
    monkeypatch.setattr("tbench.launch.THINHARNESS_COMMIT", commit)
    bundle_path = None

    with _transient_source_override() as override:
        bundle_path = override.bundle_path
        assert override.mode == "local-git-bundle-override"
        assert bundle_path is not None and bundle_path.is_file()
        assert override.bundle_sha256 == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        assert subprocess.run(["git", "bundle", "verify", str(bundle_path)], check=False).returncode == 0

    assert bundle_path is not None and not bundle_path.exists()


def test_canonical_github_is_the_default_source(monkeypatch) -> None:
    monkeypatch.delenv("TB_THINHARNESS_LOCAL_SOURCE", raising=False)

    with _transient_source_override() as override:
        assert override == SourceOverride(mode="canonical-github")
