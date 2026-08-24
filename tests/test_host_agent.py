from __future__ import annotations

import json
from pathlib import Path

import pytest

from tbench.agent import NativeThinHarnessAgent
from tbench.constants import MODEL_REF, THINHARNESS_COMMIT


class Result:
    return_code = 0
    stdout = ""
    stderr = ""


class FakeEnvironment:
    def __init__(self, preflight: dict) -> None:
        self.preflight = preflight
        self.execs: list[dict] = []
        self.uploads: list[tuple[Path, str]] = []

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        self.execs.append({"command": command, "cwd": cwd, "env": env, "timeout_sec": timeout_sec, "user": user})
        return Result()

    async def upload_file(self, source_path, target_path):
        self.uploads.append((Path(source_path), target_path))

    async def download_file(self, source_path, target_path):
        Path(target_path).write_text(json.dumps(self.preflight))


class Context:
    n_input_tokens: int | None = None
    n_cache_tokens: int | None = None
    n_output_tokens: int | None = None
    metadata: dict | None = None


@pytest.mark.asyncio
async def test_preflight_agent_only_stages_and_launches_container_process(tmp_path: Path) -> None:
    preflight = {"kind": "no-model-container-preflight", "model_calls": 0, "thinharness_commit": THINHARNESS_COMMIT}
    environment = FakeEnvironment(preflight)
    agent = NativeThinHarnessAgent(logs_dir=tmp_path, model_name=MODEL_REF, preflight_only=True)
    context = Context()

    await agent.setup(environment)  # type: ignore[arg-type]
    await agent.run("instruction", environment, context)  # type: ignore[arg-type]

    targets = {target for _, target in environment.uploads}
    assert "/opt/thinharness-terminal-bench/container_runner.py" in targets
    assert "/opt/thinharness-terminal-bench/system-prompt.md" in targets
    assert len(environment.execs) == 2
    assert environment.execs[0]["command"].startswith("mkdir -p")
    assert environment.execs[1]["command"].startswith("bash /opt/thinharness-terminal-bench/install-in-container.sh")
    assert all(item["env"] is None for item in environment.execs)
    assert context.metadata is not None
    assert context.metadata["mode"] == "no-model-preflight"
    assert context.metadata["model_requests"] == 0
    assert context.metadata["verifier_handoff"] is True


@pytest.mark.asyncio
async def test_agent_rejects_any_other_model_before_staging(tmp_path: Path) -> None:
    environment = FakeEnvironment({})
    agent = NativeThinHarnessAgent(logs_dir=tmp_path, model_name="openai/other", preflight_only=True)

    with pytest.raises(ValueError, match=MODEL_REF):
        await agent.setup(environment)  # type: ignore[arg-type]

    assert environment.uploads == []
    assert environment.execs == []
