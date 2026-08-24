"""Minimal Harbor host agent that only stages and launches the container runner."""

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

from .constants import (
    CONTAINER_LOGS,
    CONTAINER_STAGE,
    MODEL_REF,
    PROMPT_PATH,
    THINHARNESS_COMMIT,
)

_PACKAGE_DIR = Path(__file__).resolve().parent
_INSTALL_SCRIPT = _PACKAGE_DIR.parent / "scripts" / "install-in-container.sh"
_RUNTIME_REQUIREMENTS = _PACKAGE_DIR.parent / "configs" / "container-runtime-requirements.txt"
_NATIVE_TOOL_SCHEMAS = _PACKAGE_DIR.parent / "configs" / "native-tool-schemas.json"
_CONTAINER_SOURCE_BUNDLE = f"{CONTAINER_STAGE}/thinharness-source.bundle"
_STAGE_FILES = {
    _PACKAGE_DIR / "container_runner.py": f"{CONTAINER_STAGE}/container_runner.py",
    _PACKAGE_DIR / "container_security.py": f"{CONTAINER_STAGE}/container_security.py",
    _PACKAGE_DIR / "budget.py": f"{CONTAINER_STAGE}/budget.py",
    _PACKAGE_DIR / "constants.py": f"{CONTAINER_STAGE}/constants.py",
    _PACKAGE_DIR / "schema_contract.py": f"{CONTAINER_STAGE}/schema_contract.py",
    PROMPT_PATH: f"{CONTAINER_STAGE}/system-prompt.md",
    _INSTALL_SCRIPT: f"{CONTAINER_STAGE}/install-in-container.sh",
    _RUNTIME_REQUIREMENTS: f"{CONTAINER_STAGE}/container-runtime-requirements.txt",
    _NATIVE_TOOL_SCHEMAS: f"{CONTAINER_STAGE}/native-tool-schemas.json",
}


class NativeThinHarnessAgent(BaseAgent):
    """Stage the pinned wheel runner and execute it in the Harbor task container."""

    def __init__(
        self,
        *args: Any,
        preflight_only: bool = False,
        launch_id: str = "unconfigured",
        prior_implementation_spend_usd: float = 0.0,
        source_bundle_path: str | None = None,
        source_bundle_sha256: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.preflight_only = preflight_only
        self.launch_id = launch_id
        self.prior_implementation_spend_usd = prior_implementation_spend_usd
        self.source_bundle_path = Path(source_bundle_path) if source_bundle_path else None
        self.source_bundle_sha256 = source_bundle_sha256
        self._preflight: dict[str, Any] | None = None

    @staticmethod
    def name() -> str:
        return "native-thinharness"

    def version(self) -> str | None:
        return f"0.1+{THINHARNESS_COMMIT[:12]}"

    async def setup(self, environment: BaseEnvironment) -> None:
        """Stage repository controls, build the pinned wheel, and run no-model inspection."""
        if self.model_name != MODEL_REF:
            raise ValueError(f"model must be exactly {MODEL_REF}")
        created = await environment.exec(
            f"mkdir -p {shlex.quote(CONTAINER_STAGE)} {shlex.quote(CONTAINER_LOGS)}",
            cwd="/app",
            timeout_sec=30,
            user="root",
        )
        if created.return_code != 0:
            raise RuntimeError("could not create container staging directories")
        for source, target in _STAGE_FILES.items():
            await environment.upload_file(source, target)
        source_mode = "canonical-github"
        if self.source_bundle_path is not None:
            if not self.source_bundle_path.is_file() or not self.source_bundle_sha256:
                raise RuntimeError("local source bundle override is missing its file or hash")
            actual_bundle_sha256 = hashlib.sha256(self.source_bundle_path.read_bytes()).hexdigest()
            if actual_bundle_sha256 != self.source_bundle_sha256:
                raise RuntimeError("local source bundle hash differs before container staging")
            await environment.upload_file(self.source_bundle_path, _CONTAINER_SOURCE_BUNDLE)
            source_mode = "local-git-bundle-override"
        try:
            result = await environment.exec(
                f"bash {shlex.quote(CONTAINER_STAGE + '/install-in-container.sh')}",
                cwd="/app",
                timeout_sec=600,
                user="root",
            )
        finally:
            bundle_cleanup = await environment.exec(
                f"rm -f -- {shlex.quote(_CONTAINER_SOURCE_BUNDLE)}",
                cwd="/app",
                timeout_sec=30,
                user="root",
            )
        setup_receipt = {
            "schema_version": 2,
            "execution": "harbor-task-container",
            "command": "install-in-container.sh",
            "exit_code": result.return_code,
            "stdout_sha256": hashlib.sha256((result.stdout or "").encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256((result.stderr or "").encode()).hexdigest(),
            "staged_targets": sorted(_STAGE_FILES.values()),
            "source": {
                "mode": source_mode,
                "bundle_sha256": self.source_bundle_sha256,
                "container_bundle_removed": bundle_cleanup.return_code == 0,
            },
            "host_loop": False,
            "custom_model_tools": False,
        }
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if result.return_code != 0:
            self._write_setup_receipt(setup_receipt)
            detail = (result.stderr or result.stdout or "setup failed")[-4000:]
            raise RuntimeError(f"container setup failed: {detail}")
        self._preflight = await self._download_json(environment, f"{CONTAINER_LOGS}/container-preflight.json")
        setup_receipt["overflow_artifact_handoff"] = await self._download_overflow_artifact(environment, self._preflight)
        self._write_setup_receipt(setup_receipt)

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        """Launch one paid process, or return after the setup-only no-model preflight."""
        if self._preflight is None:
            raise RuntimeError("container preflight receipt is missing")
        if self.preflight_only:
            context.n_input_tokens = 0
            context.n_cache_tokens = 0
            context.n_output_tokens = 0
            context.metadata = {
                "mode": "no-model-preflight",
                "model_requests": 0,
                "tool_calls": 0,
                "container_preflight": self._preflight,
                "verifier_handoff": True,
            }
            return
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required and must be passed through the process environment")
        with tempfile.TemporaryDirectory(prefix="tbench-instruction-") as directory:
            instruction_path = Path(directory) / "instruction.txt"
            instruction_path.write_text(instruction, encoding="utf-8")
            await environment.upload_file(instruction_path, f"{CONTAINER_STAGE}/instruction.txt")
        command = (
            'exec 9<<<"$OPENAI_API_KEY"; unset OPENAI_API_KEY; '
            f"exec env -u OPENAI_API_KEY /opt/thinharness-venv/bin/python {shlex.quote(CONTAINER_STAGE + '/container_runner.py')} paid "
            f"--prompt {shlex.quote(CONTAINER_STAGE + '/system-prompt.md')} "
            f"--install-provenance {shlex.quote(CONTAINER_STAGE + '/install-provenance.json')} "
            f"--instruction {shlex.quote(CONTAINER_STAGE + '/instruction.txt')} "
            f"--ledger {shlex.quote(CONTAINER_LOGS + '/api-budget.json')} "
            f"--receipt {shlex.quote(CONTAINER_LOGS + '/native-thinharness-result.json')} "
            f"--launch-id {shlex.quote(self.launch_id)} "
            f"--prior-spend {self.prior_implementation_spend_usd!r} "
            "--credential-fd 9"
        )
        try:
            result = await environment.exec(
                command,
                cwd="/app",
                env={"OPENAI_API_KEY": api_key},
                timeout_sec=900,
                user="root",
            )
        finally:
            for name in ("api-budget.json", "native-thinharness-result.json"):
                try:
                    await self._download_json(environment, f"{CONTAINER_LOGS}/{name}")
                except Exception:
                    pass
        if result.return_code != 0:
            detail = (result.stderr or result.stdout or "container runner failed")[-4000:]
            raise RuntimeError(f"container ThinHarness process failed: {detail}")
        receipt = await self._download_json(environment, f"{CONTAINER_LOGS}/native-thinharness-result.json")
        usage = receipt.get("usage") or {}
        context.n_input_tokens = int(usage.get("input_tokens", 0))
        context.n_cache_tokens = int(usage.get("cached_tokens", 0))
        context.n_output_tokens = int(usage.get("output_tokens", 0))
        context.metadata = {
            "model_requests": usage.get("model_requests"),
            "tool_calls": usage.get("tool_calls"),
            "stop_reason": receipt.get("stop_reason"),
            "response_models": receipt.get("response_models"),
            "api_equivalent_cost_usd": receipt.get("api_equivalent_cost_usd"),
            "container_execution": receipt.get("execution"),
            "verifier_handoff": True,
        }

    def _write_setup_receipt(self, value: dict[str, Any]) -> None:
        (self.logs_dir / "host-agent-setup.json").write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    async def _download_overflow_artifact(self, environment: BaseEnvironment, preflight: dict[str, Any]) -> dict[str, Any]:
        overflow = preflight.get("native_bash_overflow") or {}
        relative_path = overflow.get("artifact_path")
        expected_sha256 = overflow.get("full_output_sha256")
        expected_bytes = overflow.get("full_output_bytes")
        if not isinstance(relative_path, str) or not relative_path.startswith(".thinharness/outputs/"):
            raise RuntimeError("container preflight overflow artifact path is invalid")
        source = f"/app/{relative_path}"
        target = self.logs_dir / "bash-overflow-full.bin"
        await environment.download_file(source, target)
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_sha256 or len(content) != expected_bytes:
            raise RuntimeError("durable Bash overflow artifact differs from container receipt")
        cleanup_command = (
            f"rm -f -- {shlex.quote(source)} && "
            "rmdir --ignore-fail-on-non-empty /app/.thinharness/outputs /app/.thinharness 2>/dev/null || true"
        )
        cleanup = await environment.exec(cleanup_command, cwd="/app", timeout_sec=30)
        return {
            "source_path": source,
            "durable_path": "bash-overflow-full.bin",
            "sha256": expected_sha256,
            "bytes": expected_bytes,
            "verified": True,
            "container_artifact_removed": cleanup.return_code == 0,
        }

    async def _download_json(self, environment: BaseEnvironment, source: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="tbench-receipt-") as directory:
            local_path = Path(directory) / Path(source).name
            await environment.download_file(source, local_path)
            content = local_path.read_bytes()
        target = self.logs_dir / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        value = json.loads(content)
        if not isinstance(value, dict):
            raise RuntimeError(f"container receipt is not an object: {source}")
        return value
