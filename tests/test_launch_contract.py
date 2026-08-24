from __future__ import annotations

from tbench.constants import DATASET_DIGEST, MODEL_REF, TASK_NAME
from tbench.launch import harbor_command


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
