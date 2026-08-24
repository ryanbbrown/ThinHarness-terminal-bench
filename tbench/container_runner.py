"""Process entry point staged into the Harbor task container."""

# pyright: reportMissingImports=false

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import socket
import sys
import time
from pathlib import Path
from typing import Any

from budget import BudgetError, finalize_ledger, initialize_ledger, reserve_request, settle_request
from constants import (
    AGENT_OUTPUT_RETRIES,
    AGENT_TOOL_RETRIES,
    ATTEMPT_BUDGET_USD,
    CONTAINER_ROOT,
    DATASET_DIGEST,
    IMPLEMENTATION_BUDGET_USD,
    MAX_MODEL_REQUESTS,
    MAX_TOOL_CALLS,
    MODEL_ID,
    OPENAI_BASE_URL,
    PROMPT_SHA256,
    PROVIDER_RETRIES,
    REASONING,
    TASK_NAME,
    TEXT,
    THINHARNESS_COMMIT,
)
from container_security import harden_linux_model_loop_parent, read_handoff_fd
from schema_contract import validate_native_tool_schemas


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, default=str)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _load_prompt(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    digest = _sha256_bytes(value.encode("utf-8"))
    if digest != PROMPT_SHA256:
        raise RuntimeError(f"frozen prompt hash mismatch: {digest}")
    return value


def _staged_control_hashes() -> dict[str, str]:
    stage = Path(__file__).resolve().parent
    names = (
        "budget.py",
        "constants.py",
        "container_runner.py",
        "container_security.py",
        "container-runtime-requirements.txt",
        "install-in-container.sh",
        "native-tool-schemas.json",
        "schema_contract.py",
        "system-prompt.md",
    )
    result = {}
    for name in names:
        path = stage / name
        if not path.is_file():
            raise RuntimeError(f"staged control is missing: {name}")
        result[name] = _sha256_bytes(path.read_bytes())
    return result


async def _native_bash_credential_isolation(harness: Any) -> dict[str, Any]:
    bash_tool = next((tool for tool in harness.tools if tool.name == "bash"), None)
    if bash_tool is None:
        raise RuntimeError("native Bash tool is missing for credential isolation preflight")
    command = """set -eu
if printenv OPENAI_API_KEY >/dev/null 2>&1 || printenv TB_CREDENTIAL_SENTINEL >/dev/null 2>&1; then
  exit 41
fi
error_file="$(mktemp)"
trap 'rm -f "$error_file"' EXIT
if cat "/proc/$PPID/environ" >/dev/null 2>"$error_file"; then
  exit 42
fi
if ! grep -qi 'permission denied' "$error_file"; then
  exit 43
fi
printf 'credential isolation verified\\n'
"""
    args = bash_tool.parameters.model_validate({"command": command, "cwd": CONTAINER_ROOT, "timeout": 10})
    result = await bash_tool.handler(args)
    if not result.ok:
        raise RuntimeError(f"native Bash credential isolation failed: {result.content}")
    return {
        "native_tool": "bash",
        "own_environment_openai_key_absent": True,
        "own_environment_sentinel_absent": True,
        "parent_environ_read_blocked": True,
        "result": {"ok": result.ok, "content": result.content, "metadata": result.metadata},
    }


def _environment_identity() -> dict[str, Any]:
    os_release: dict[str, str] = {}
    release_path = Path("/etc/os-release")
    if release_path.exists():
        for line in release_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                os_release[key] = value.strip('"')
    cgroup = Path("/proc/1/cgroup")
    return {
        "execution": "harbor-task-container",
        "cwd": str(Path.cwd().resolve()),
        "workspace_root": str(Path(CONTAINER_ROOT).resolve()),
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "pid1_cgroup_sha256": _sha256_bytes(cgroup.read_bytes()) if cgroup.exists() else None,
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "os_release": {key: os_release.get(key) for key in ("ID", "VERSION_ID", "PRETTY_NAME")},
    }


def _reported_cash_total(ledger: dict[str, Any] | None) -> float | None:
    if ledger is None:
        return None
    requests = ledger.get("requests")
    if not isinstance(requests, list) or not requests:
        return None
    total = 0.0
    for request in requests:
        if not isinstance(request, dict):
            return None
        cost = request.get("reported_cash_cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, int | float):
            return None
        total += float(cost)
    return total


def _install_provenance(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("canonical_commit") != THINHARNESS_COMMIT:
        raise RuntimeError("installed ThinHarness commit does not match the canonical pin")
    wheel_path = Path(value["wheel_path"])
    if not wheel_path.is_file() or _sha256_bytes(wheel_path.read_bytes()) != value.get("wheel_sha256"):
        raise RuntimeError("installed ThinHarness wheel hash does not match its provenance")
    return value


def _build_harness(*, prompt: str, provider: Any) -> Any:
    from thinharness import BashPlugin, FilesystemPlugin, Harness, HarnessConfig, ModelSettings, OpenAIResponsesModel

    settings = ModelSettings(
        effort=REASONING["effort"],
        extra_body={"reasoning": dict(REASONING), "text": dict(TEXT)},
    )
    model = OpenAIResponsesModel(MODEL_ID, provider=provider, settings=settings)
    return Harness(
        HarnessConfig(
            model=f"openai:{MODEL_ID}",
            root=CONTAINER_ROOT,
            system_prompt=prompt,
            max_model_requests=MAX_MODEL_REQUESTS,
            max_tool_calls=MAX_TOOL_CALLS,
            request_timeout=900,
            request_retries=PROVIDER_RETRIES,
            request_retry_backoff=0,
            effort=REASONING["effort"],
            extra_body={"reasoning": dict(REASONING), "text": dict(TEXT)},
            output_retries=AGENT_OUTPUT_RETRIES,
            tool_retries=AGENT_TOOL_RETRIES,
            tool_execution="sequential",
            local_tracing=False,
        ),
        model=model,
        plugins=[
            BashPlugin(default_timeout=120, max_timeout=300, max_output_bytes=40_000, inherit_env=False),
            FilesystemPlugin(tools=["read", "edit", "write"]),
        ],
    )


def _wire_probe(harness: Any) -> dict[str, Any]:
    """Build one sanitized payload through the installed OpenAI model without sending it."""
    payload = harness.model.build_payload(
        input_payload="NO_MODEL_PREFLIGHT",
        tools=harness.tool_schemas(),
        instructions="NO_MODEL_PREFLIGHT",
    )
    expected = {
        "model": MODEL_ID,
        "reasoning": REASONING,
        "text": TEXT,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"OpenAI payload probe has unexpected {key}: {payload.get(key)!r}")
    if "max_output_tokens" in payload:
        raise RuntimeError("preflight payload unexpectedly has a static output allowance")
    return {
        "model": payload["model"],
        "reasoning": payload["reasoning"],
        "text": payload["text"],
        "tool_names": [tool["name"] for tool in payload["tools"]],
        "dynamic_budget_sets_max_output_tokens": True,
        "network_requests": 0,
    }


def _tool_evidence(harness: Any) -> dict[str, Any]:
    schemas = harness.tool_schemas()
    names = [schema["name"] for schema in schemas]
    if set(names) != {"bash", "read", "edit", "write"} or len(names) != 4:
        raise RuntimeError(f"unexpected native tool surface: {names}")
    schema_hashes = validate_native_tool_schemas(
        schemas,
        Path(__file__).resolve().parent / "native-tool-schemas.json",
    )
    origins = {
        tool.name: {
            "plugin": tool.origin.plugin if tool.origin else None,
            "source": tool.origin.source if tool.origin else None,
        }
        for tool in harness.tools
    }
    expected_origins = {
        "bash": {"plugin": "bash", "source": "bash"},
        "read": {"plugin": "filesystem", "source": "read"},
        "edit": {"plugin": "filesystem", "source": "edit"},
        "write": {"plugin": "filesystem", "source": "write"},
    }
    if origins != expected_origins:
        raise RuntimeError(f"tools are not canonical plugin contributions: {origins}")
    return {"names": names, "origins": origins, "schema_sha256": schema_hashes, "schemas": schemas}


class BudgetedDirectOpenAIProvider:
    """Construct the canonical provider lazily after ThinHarness is installed."""

    @staticmethod
    def create(*, ledger_path: Path, api_key: str) -> Any:
        from thinharness import OpenAIProvider
        from thinharness.providers import ProviderError

        class Provider(OpenAIProvider):
            def __init__(self) -> None:
                super().__init__(
                    api_key=api_key,
                    base_url=OPENAI_BASE_URL,
                    timeout=900,
                    request_retries=PROVIDER_RETRIES,
                    request_retry_backoff=0,
                )
                self._prior_input_tokens = 0
                self._prior_output_tokens = 0

            async def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
                expected_reasoning = dict(REASONING)
                expected_text = dict(TEXT)
                if self.base_url != OPENAI_BASE_URL:
                    raise ProviderError("direct OpenAI base URL identity check failed")
                if payload.get("model") != MODEL_ID:
                    raise ProviderError("request model identity check failed")
                if payload.get("reasoning") != expected_reasoning:
                    raise ProviderError("reasoning wire settings differ from the frozen settings")
                if payload.get("text") != expected_text:
                    raise ProviderError("text wire settings differ from the frozen settings")
                serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                try:
                    reservation = reserve_request(
                        ledger_path,
                        payload_bytes=len(serialized),
                        payload_sha256=_sha256_bytes(serialized),
                        prior_input_tokens=self._prior_input_tokens,
                        prior_output_tokens=self._prior_output_tokens,
                    )
                except BudgetError as exc:
                    raise ProviderError(str(exc)) from exc
                request_payload = dict(payload)
                request_payload["max_output_tokens"] = reservation.max_output_tokens
                response = await super().create_response(request_payload)
                usage = response.get("usage")
                if response.get("model") != MODEL_ID:
                    raise ProviderError("response model identity check failed")
                if not isinstance(usage, dict):
                    raise ProviderError("OpenAI response omitted usage")
                input_tokens = usage.get("input_tokens")
                output_tokens = usage.get("output_tokens")
                input_details = usage.get("input_tokens_details")
                output_details = usage.get("output_tokens_details")
                if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
                    raise ProviderError("OpenAI response omitted input or output tokens")
                if not isinstance(input_details, dict) or not isinstance(input_details.get("cached_tokens"), int):
                    raise ProviderError("OpenAI response omitted cached token details")
                if not isinstance(output_details, dict) or not isinstance(output_details.get("reasoning_tokens"), int):
                    raise ProviderError("OpenAI response omitted reasoning token details")
                cached_tokens = input_details["cached_tokens"]
                cache_write_value = input_details.get("cache_write_tokens", 0)
                if not isinstance(cache_write_value, int):
                    raise ProviderError("OpenAI response has invalid cache-write token details")
                ordinary_tokens = input_tokens - cached_tokens - cache_write_value
                reported_cost = usage.get("cost_usd")
                try:
                    settle_request(
                        ledger_path,
                        request_id=reservation.request_id,
                        response_model=response["model"],
                        input_tokens=input_tokens,
                        ordinary_input_tokens=ordinary_tokens,
                        cached_input_tokens=cached_tokens,
                        cache_write_tokens=cache_write_value,
                        output_tokens=output_tokens,
                        reasoning_tokens=output_details["reasoning_tokens"],
                        reported_cost_usd=reported_cost if isinstance(reported_cost, int | float) else None,
                    )
                except BudgetError as exc:
                    raise ProviderError(str(exc)) from exc
                self._prior_input_tokens = input_tokens
                self._prior_output_tokens = output_tokens
                return response

        return Provider()


async def preflight(args: argparse.Namespace) -> int:
    from thinharness import OpenAIProvider, __version__

    security = harden_linux_model_loop_parent()
    sentinel = read_handoff_fd(args.sentinel_fd, label="credential sentinel")
    if "OPENAI_API_KEY" in os.environ or "TB_CREDENTIAL_SENTINEL" in os.environ:
        raise RuntimeError("credential handoff remained in ordinary process inheritance")
    prompt = _load_prompt(args.prompt)
    provenance = _install_provenance(args.install_provenance)
    provider = OpenAIProvider(
        api_key=None,
        base_url=OPENAI_BASE_URL,
        timeout=900,
        request_retries=PROVIDER_RETRIES,
        request_retry_backoff=0,
    )
    harness = _build_harness(prompt=prompt, provider=provider)
    receipt = {
        "schema_version": 1,
        "kind": "no-model-container-preflight",
        "model_calls": 0,
        "passed": True,
        "thinharness": {
            "version": __version__,
            "canonical_commit": THINHARNESS_COMMIT,
            "install": provenance,
        },
        "execution": _environment_identity(),
        "credential_isolation": {
            "ordinary_inheritance_removed": True,
            "sentinel_sha256": _sha256_bytes(sentinel.encode("utf-8")),
            "process_security": security,
            "native_bash": await _native_bash_credential_isolation(harness),
        },
        "staged_control_sha256": _staged_control_hashes(),
        "root": str(harness.root),
        "tools": _tool_evidence(harness),
        "prompt": {"path": str(args.prompt), "sha256": PROMPT_SHA256},
        "wire": {
            "provider": "openai",
            "base_url": provider.base_url,
            "model": MODEL_ID,
            "reasoning": REASONING,
            "text": TEXT,
            "provider_retries": provider.request_retries,
            "agent_output_retries": harness.config.output_retries,
            "agent_tool_retries": harness.config.tool_retries,
            "payload_probe": _wire_probe(harness),
        },
        "limits": {
            "max_model_requests": harness.config.max_model_requests,
            "max_tool_calls": harness.config.max_tool_calls,
        },
        "verifier_handoff": {
            "workspace": CONTAINER_ROOT,
            "agent_returns_before_harbor_verifier": True,
            "harbor_owns_verifier": True,
        },
    }
    _atomic_json(args.receipt, receipt)
    return 0


async def _paid(args: argparse.Namespace) -> int:
    from thinharness import __version__

    security = harden_linux_model_loop_parent()
    if "OPENAI_API_KEY" in os.environ:
        raise RuntimeError("OPENAI_API_KEY must not enter ordinary model-loop inheritance")
    key = read_handoff_fd(args.credential_fd, label="OpenAI credential")
    prompt = _load_prompt(args.prompt)
    instruction = args.instruction.read_text(encoding="utf-8")
    provenance = _install_provenance(args.install_provenance)
    initialize_ledger(
        args.ledger,
        launch_id=args.launch_id,
        dataset_digest=DATASET_DIGEST,
        task=TASK_NAME,
        model=MODEL_ID,
        attempt_ceiling_usd=ATTEMPT_BUDGET_USD,
        implementation_ceiling_usd=IMPLEMENTATION_BUDGET_USD,
        prior_implementation_spend_usd=args.prior_spend,
    )
    provider = BudgetedDirectOpenAIProvider.create(ledger_path=args.ledger, api_key=key)
    harness = _build_harness(prompt=prompt, provider=provider)
    started = time.perf_counter()
    result = None
    error = None
    try:
        result = await harness.run(instruction, metadata={"launch_id": args.launch_id, "task": TASK_NAME})
        finalize_ledger(args.ledger, success=result.stop_reason == "end_turn")
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        elapsed = time.perf_counter() - started
        ledger = json.loads(args.ledger.read_text(encoding="utf-8")) if args.ledger.exists() else None
        tool_records = result.tool_call_records if result is not None else []
        tool_names = [record.get("call", {}).get("name") for record in tool_records]
        response_model_set: set[str] = set()
        for response in result.responses if result is not None else []:
            if isinstance(response, dict):
                response_model = response.get("model")
                if isinstance(response_model, str):
                    response_model_set.add(response_model)
        response_models = sorted(response_model_set)
        receipt = {
            "schema_version": 1,
            "kind": "paid-native-thinharness-attempt",
            "launch_id": args.launch_id,
            "task": TASK_NAME,
            "dataset_digest": DATASET_DIGEST,
            "thinharness": {"version": __version__, "canonical_commit": THINHARNESS_COMMIT, "install": provenance},
            "execution": _environment_identity(),
            "credential_isolation": {
                "ordinary_inheritance_removed": True,
                "process_security": security,
            },
            "staged_control_sha256": _staged_control_hashes(),
            "prompt_sha256": PROMPT_SHA256,
            "wire": {
                "provider": "openai",
                "base_url": OPENAI_BASE_URL,
                "model": MODEL_ID,
                "reasoning": REASONING,
                "text": TEXT,
                "provider_retries": PROVIDER_RETRIES,
                "agent_output_retries": AGENT_OUTPUT_RETRIES,
                "agent_tool_retries": AGENT_TOOL_RETRIES,
            },
            "root": str(harness.root),
            "tools": _tool_evidence(harness),
            "agent_time_seconds": elapsed,
            "stop_reason": result.stop_reason if result is not None else None,
            "text": result.text if result is not None else None,
            "usage": result.usage.to_json() if result is not None else None,
            "response_models": response_models,
            "tool_names": tool_names,
            "tool_call_records": tool_records,
            "api_budget": ledger,
            "actual_cash_cost_usd": _reported_cash_total(ledger),
            "api_equivalent_cost_usd": (ledger or {}).get("spent_usd"),
            "cost_basis": "provider-reported cash when complete; otherwise GPT-5.6 Sol API-equivalent token pricing",
            "error": error,
            "verifier_handoff": {"workspace": CONTAINER_ROOT, "ready": result is not None},
        }
        _atomic_json(args.receipt, receipt)
        await harness.aclose()
        await provider.aclose()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "paid"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--prompt", type=Path, required=True)
        sub.add_argument("--install-provenance", type=Path, required=True)
        sub.add_argument("--receipt", type=Path, required=True)
        if command == "preflight":
            sub.add_argument("--sentinel-fd", type=int, required=True)
        if command == "paid":
            sub.add_argument("--instruction", type=Path, required=True)
            sub.add_argument("--ledger", type=Path, required=True)
            sub.add_argument("--launch-id", required=True)
            sub.add_argument("--prior-spend", type=float, required=True)
            sub.add_argument("--credential-fd", type=int, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "preflight":
        return asyncio.run(preflight(args))
    return asyncio.run(_paid(args))


if __name__ == "__main__":
    raise SystemExit(main())
