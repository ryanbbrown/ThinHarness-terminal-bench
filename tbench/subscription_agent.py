"""Harbor stage-and-launch agent for matched Pi and ThinHarness subscription cells."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .subscription_constants import (
    CONTAINER_LOGS,
    CONTAINER_STAGE,
    GATEWAY_TOKEN_ENV,
    GATEWAY_URL_ENV,
    MODEL,
    SOURCE_BUNDLE_ENV,
    SOURCE_BUNDLE_SHA_ENV,
    SUBSCRIPTION_PROMPT_PATH,
    THINHARNESS_COMMIT,
)

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE = Path(__file__).resolve().parent
_COMMON_FILES = {
    _PACKAGE / "subscription_container.py": f"{CONTAINER_STAGE}/subscription_container.py",
    _PACKAGE / "container_security.py": f"{CONTAINER_STAGE}/container_security.py",
    SUBSCRIPTION_PROMPT_PATH: f"{CONTAINER_STAGE}/system-prompt.md",
}
_THIN_FILES = {
    _ROOT / "scripts" / "install-subscription-thinharness.sh": f"{CONTAINER_STAGE}/install.sh",
    _ROOT / "configs" / "container-runtime-requirements.txt": f"{CONTAINER_STAGE}/container-runtime-requirements.txt",
}
_PI_FILES = {
    _ROOT / "scripts" / "install-subscription-pi.sh": f"{CONTAINER_STAGE}/install.sh",
    _ROOT / "configs" / "pi-subscription-package.json": f"{CONTAINER_STAGE}/pi-subscription-package.json",
    _ROOT / "configs" / "pi-subscription-package-lock.json": f"{CONTAINER_STAGE}/pi-subscription-package-lock.json",
    _PACKAGE / "pi_subscription_probe.mjs": f"{CONTAINER_STAGE}/pi_subscription_probe.mjs",
}


class SubscriptionSmokeAgent(BaseAgent):
    """Install and run one native harness loop in the Harbor task container."""

    def __init__(
        self,
        *args: Any,
        harness: str,
        cell_id: str,
        mode: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if harness not in {"pi", "thinharness"}:
            raise ValueError("harness must be pi or thinharness")
        if mode not in {"fake", "real"}:
            raise ValueError("mode must be fake or real")
        self.harness = harness
        self.cell_id = cell_id
        self.mode = mode
        self.setup_receipt: dict[str, Any] | None = None

    @staticmethod
    def name() -> str:
        return "matched-subscription-smoke"

    def version(self) -> str | None:
        return f"1.0+{THINHARNESS_COMMIT[:8]}"

    async def setup(self, environment: BaseEnvironment) -> None:
        if self.model_name != f"openai/{MODEL}":
            raise RuntimeError("subscription smoke model identity differs")
        created = await environment.exec(
            f"mkdir -p {shlex.quote(CONTAINER_STAGE)} {shlex.quote(CONTAINER_LOGS)}",
            cwd="/app",
            timeout_sec=30,
            user="root",
        )
        if created.return_code != 0:
            raise RuntimeError("could not create subscription staging paths")
        staged = dict(_COMMON_FILES)
        staged.update(_PI_FILES if self.harness == "pi" else _THIN_FILES)
        for source, target in staged.items():
            await environment.upload_file(source, target)
        bundle_hash = None
        if self.harness == "thinharness":
            raw = os.getenv(SOURCE_BUNDLE_ENV)
            bundle_hash = os.getenv(SOURCE_BUNDLE_SHA_ENV)
            if not raw or not bundle_hash:
                raise RuntimeError("ThinHarness subscription cell requires the transient exact-commit source bundle")
            bundle = Path(raw)
            if not bundle.is_file() or hashlib.sha256(bundle.read_bytes()).hexdigest() != bundle_hash:
                raise RuntimeError("ThinHarness transient source bundle is missing or changed")
            await environment.upload_file(bundle, f"{CONTAINER_STAGE}/thinharness-source.bundle")
        result = await environment.exec(
            f"bash {shlex.quote(CONTAINER_STAGE + '/install.sh')}",
            cwd="/app",
            timeout_sec=600,
            user="root",
        )
        install = None
        if result.return_code == 0:
            install = await self._download_json(environment, f"{CONTAINER_STAGE}/install-provenance.json", "install-provenance.json")
        cleanup = await environment.exec(
            f"rm -f -- {shlex.quote(CONTAINER_STAGE + '/thinharness-source.bundle')}",
            cwd="/app",
            timeout_sec=30,
            user="root",
        )
        self.setup_receipt = {
            "schema_version": 1,
            "cell_id": self.cell_id,
            "harness": self.harness,
            "execution": "harbor-task-container",
            "stage_and_launch_only": True,
            "host_model_loop": False,
            "custom_host_tools": False,
            "staged_targets": sorted(staged.values()),
            "install_exit_code": result.return_code,
            "install_stdout_sha256": hashlib.sha256((result.stdout or "").encode()).hexdigest(),
            "install_stderr_sha256": hashlib.sha256((result.stderr or "").encode()).hexdigest(),
            "install": install,
            "source_bundle_sha256": bundle_hash,
            "source_bundle_container_removed": cleanup.return_code == 0,
        }
        self._write_json("host-agent-setup.json", self.setup_receipt)
        if result.return_code != 0:
            detail = (result.stderr or result.stdout or "installation failed")[-4000:]
            raise RuntimeError(f"subscription container install failed: {detail}")

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        if self.setup_receipt is None:
            raise RuntimeError("subscription setup receipt is absent")
        gateway_url = os.getenv(GATEWAY_URL_ENV)
        gateway_token = os.getenv(GATEWAY_TOKEN_ENV)
        if not gateway_url or not gateway_token:
            raise RuntimeError("ephemeral subscription gateway environment is absent")
        if os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("direct OpenAI API credentials are forbidden for subscription smoke")
        with tempfile.TemporaryDirectory(prefix="subscription-instruction-") as directory:
            source = Path(directory) / "instruction.txt"
            source.write_text(instruction, encoding="utf-8")
            await environment.upload_file(source, f"{CONTAINER_STAGE}/instruction.txt")
        receipt_name = f"{self.harness}-subscription-result.json"
        events_name = f"{self.harness}-events.jsonl"
        stderr_name = f"{self.harness}-stderr.log"
        python = "/opt/thinharness-subscription-venv/bin/python" if self.harness == "thinharness" else "/usr/bin/python3"
        command = (
            f"{python} {shlex.quote(CONTAINER_STAGE + '/subscription_container.py')} {self.harness} "
            f"--cell-id {shlex.quote(self.cell_id)} "
            f"--prompt {shlex.quote(CONTAINER_STAGE + '/system-prompt.md')} "
            f"--instruction {shlex.quote(CONTAINER_STAGE + '/instruction.txt')} "
            f"--install-provenance {shlex.quote(CONTAINER_STAGE + '/install-provenance.json')} "
            f"--receipt {shlex.quote(CONTAINER_LOGS + '/' + receipt_name)} "
            f"--events {shlex.quote(CONTAINER_LOGS + '/' + events_name)} "
            f"--stderr {shlex.quote(CONTAINER_LOGS + '/' + stderr_name)}"
        )
        result = await environment.exec(
            command,
            cwd="/app",
            env={
                GATEWAY_URL_ENV: gateway_url,
                GATEWAY_TOKEN_ENV: gateway_token,
                "TB_SUBSCRIPTION_MODE": self.mode,
            },
            timeout_sec=1800,
            user="root",
        )
        for name in (receipt_name, events_name, stderr_name):
            try:
                await self._download(environment, f"{CONTAINER_LOGS}/{name}", name)
            except Exception:
                if name == receipt_name:
                    raise
        if result.return_code != 0:
            detail = (result.stderr or result.stdout or "subscription runner failed")[-4000:]
            raise RuntimeError(f"{self.harness} subscription runner failed: {detail}")
        receipt = json.loads((self.logs_dir / receipt_name).read_text(encoding="utf-8"))
        usage = receipt.get("usage") or {}
        context.n_input_tokens = int(usage.get("input_tokens", 0))
        context.n_cache_tokens = int(usage.get("cached_tokens", usage.get("cached_input_tokens", 0)))
        context.n_output_tokens = int(usage.get("output_tokens", 0))
        context.metadata = {
            "cell_id": self.cell_id,
            "harness": self.harness,
            "backend": receipt.get("backend"),
            "model_requests": receipt.get("request_count"),
            "tool_calls": receipt.get("tool_count"),
            "response_models": receipt.get("response_models"),
            "verifier_handoff": True,
        }

    def _write_json(self, name: str, value: dict[str, Any]) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    async def _download_json(self, environment: BaseEnvironment, source: str, name: str) -> dict[str, Any]:
        await self._download(environment, source, name)
        value = json.loads((self.logs_dir / name).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"container JSON is not an object: {source}")
        return value

    async def _download(self, environment: BaseEnvironment, source: str, name: str) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        target = self.logs_dir / name
        await environment.download_file(source, target)
