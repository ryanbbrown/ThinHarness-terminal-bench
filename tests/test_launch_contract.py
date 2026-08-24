from __future__ import annotations

import json
from pathlib import Path

import pytest

from tbench.constants import DATASET_DIGEST, MODEL_REF, TASK_NAME
from tbench.launch import (
    _exclusive_paid_launch,
    _load_committed_paid_result,
    _load_prior_state,
    _run_unlocked,
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


def test_unsettled_prior_launch_fails_closed(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "implementation-budget.json"
    state.write_text(json.dumps({"status": "launched"}))
    monkeypatch.setattr("tbench.launch.IMPLEMENTATION_STATE", state)
    monkeypatch.setattr("tbench.launch.COMMITTED_PAID_ARTIFACTS", tmp_path / "absent")

    with pytest.raises(RuntimeError, match="no settled receipt"):
        _load_prior_state()


def test_concurrent_paid_launch_is_excluded(tmp_path: Path) -> None:
    lock = tmp_path / "paid.lock"

    with _exclusive_paid_launch(lock):
        with pytest.raises(RuntimeError, match="exclusive launch lock"):
            with _exclusive_paid_launch(lock):
                pass


def test_fresh_checkout_reads_corrected_committed_spend() -> None:
    result, spend = _load_committed_paid_result()

    assert result is not None
    assert result["reward"] == 1.0
    assert spend == pytest.approx(0.12674175)


def test_committed_verifier_pass_refuses_another_paid_task(monkeypatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: pytest.fail("Harbor must not start after a committed verifier pass"),
    )

    with pytest.raises(RuntimeError, match="already passed its verifier"):
        _run_unlocked("paid")
