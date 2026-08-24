"""In-container Pi and ThinHarness runners for the matched subscription smoke."""

# pyright: reportMissingImports=false

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from container_security import harden_linux_model_loop_parent
except ModuleNotFoundError:  # Host-side unit tests import through the package.
    from .container_security import harden_linux_model_loop_parent

MODEL = "gpt-5.6-sol"
PROMPT_SHA256 = "bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e"
REASONING = {"effort": "xhigh", "summary": "auto"}
TEXT = {"verbosity": "low"}
ROOT = "/app"


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


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_prompt(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if _sha256(value.encode()) != PROMPT_SHA256:
        raise RuntimeError("frozen prompt hash differs")
    return value


def _identity() -> dict[str, Any]:
    release: dict[str, str] = {}
    for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    return {
        "execution": "harbor-task-container",
        "cwd": str(Path.cwd().resolve()),
        "root": ROOT,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "uid": os.getuid(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "os_release": {key: release.get(key) for key in ("ID", "VERSION_ID", "PRETTY_NAME")},
    }


def _gateway() -> tuple[str, str, str]:
    url = os.environ.pop("TB_SUBSCRIPTION_GATEWAY_URL", "")
    token = os.environ.pop("TB_SUBSCRIPTION_GATEWAY_TOKEN", "")
    mode = os.environ.pop("TB_SUBSCRIPTION_MODE", "")
    if not url.startswith("http://host.docker.internal:") or not url.endswith("/v1"):
        raise RuntimeError("subscription gateway URL is not the controlled Docker-host route")
    if len(token) < 32:
        raise RuntimeError("ephemeral subscription gateway token is missing")
    if mode not in {"fake", "real"}:
        raise RuntimeError("subscription mode must be fake or real")
    if os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("direct OpenAI API credentials are forbidden")
    return url, token, mode


def _usage_from_response(response: dict[str, Any]) -> dict[str, Any]:
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": input_details.get("cached_tokens"),
        "cache_write_tokens": input_details.get("cache_write_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": output_details.get("reasoning_tokens"),
    }


async def _run_thinharness(args: argparse.Namespace, *, url: str, token: str, mode: str) -> int:
    import httpx
    from thinharness import (
        BashPlugin,
        FilesystemPlugin,
        Harness,
        HarnessConfig,
        ModelSettings,
        OpenAIProvider,
        OpenAIResponsesModel,
        __version__,
    )
    from thinharness.providers import ProviderError

    security = harden_linux_model_loop_parent()
    requests: list[dict[str, Any]] = []

    class SubscriptionProvider(OpenAIProvider):
        def __init__(self) -> None:
            client = httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"})
            super().__init__(api_key=token, base_url=url, timeout=1800, request_retries=0, request_retry_backoff=0, http_client=client)

        async def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
            if payload.get("model") != MODEL or payload.get("reasoning") != REASONING or payload.get("text") != TEXT:
                raise ProviderError("ThinHarness subscription payload differs from frozen model settings")
            response = await super().create_response(payload)
            if response.get("model") != MODEL:
                raise ProviderError("subscription backend response model identity differs")
            usage = _usage_from_response(response)
            if not all(isinstance(usage[key], int) for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens")):
                raise ProviderError("subscription backend response usage is incomplete")
            requests.append({"sequence": len(requests) + 1, "payload": payload, "response": response, "usage": usage})
            return response

    prompt = _load_prompt(args.prompt)
    instruction = args.instruction.read_text(encoding="utf-8")
    install = json.loads(args.install_provenance.read_text(encoding="utf-8"))
    provider = SubscriptionProvider()
    settings = ModelSettings(effort="xhigh", extra_body={"reasoning": dict(REASONING), "text": dict(TEXT)})
    harness = Harness(
        HarnessConfig(
            model=f"openai:{MODEL}",
            root=ROOT,
            system_prompt=prompt,
            max_model_requests=64,
            max_tool_calls=128,
            request_timeout=1800,
            request_retries=0,
            request_retry_backoff=0,
            effort="xhigh",
            extra_body={"reasoning": dict(REASONING), "text": dict(TEXT)},
            output_retries=0,
            tool_retries=0,
            tool_execution="sequential",
            local_tracing=False,
        ),
        model=OpenAIResponsesModel(MODEL, provider=provider, settings=settings),
        plugins=[
            BashPlugin(default_timeout=120, max_timeout=300, max_output_bytes=40_000, inherit_env=False),
            FilesystemPlugin(tools=["read", "edit", "write"]),
        ],
    )
    started = time.perf_counter()
    result = None
    error = None
    try:
        result = await harness.run(instruction, metadata={"cell_id": args.cell_id, "route": "cproxy-codex-subscription"})
    except BaseException as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        elapsed = time.perf_counter() - started
        tools = harness.tool_schemas()
        tool_records = result.tool_call_records if result is not None else []
        receipt = {
            "schema_version": 1,
            "kind": "subscription-smoke-cell",
            "cell_id": args.cell_id,
            "harness": "thinharness",
            "mode": mode,
            "backend": "cproxy-codex-subscription" if mode == "real" else "controlled-fake-cproxy-contract",
            "gateway_base_url": url,
            "direct_openai": False,
            "codex_oauth_in_container": False,
            "model": MODEL,
            "reasoning": REASONING,
            "text": TEXT,
            "prompt_sha256": PROMPT_SHA256,
            "execution": _identity(),
            "process_security": security,
            "install": install,
            "harness_version": __version__,
            "thinharness_commit": install.get("canonical_commit"),
            "tool_names": [tool["name"] for tool in tools],
            "tool_schemas": tools,
            "tool_origins": {
                tool.name: {"plugin": tool.origin.plugin if tool.origin else None, "source": tool.origin.source if tool.origin else None}
                for tool in harness.tools
            },
            "requests": requests,
            "request_count": len(requests),
            "response_models": sorted(
                {item["response"].get("model") for item in requests if isinstance(item["response"].get("model"), str)}
            ),
            "tool_call_records": tool_records,
            "tool_count": len(tool_records),
            "tool_call_names": [record.get("call", {}).get("name") for record in tool_records],
            "usage": result.usage.to_json() if result is not None else None,
            "responses": result.responses if result is not None else [],
            "stop_reason": result.stop_reason if result is not None else None,
            "text_output": result.text if result is not None else None,
            "agent_seconds": elapsed,
            "retries": {"provider": 0, "agent_output": 0, "agent_tool": 0},
            "error": error,
            "verifier_handoff": {"ready": result is not None, "workspace": ROOT},
        }
        _atomic_json(args.receipt, receipt)
        args.events.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in requests), encoding="utf-8")
        args.stderr.write_text("", encoding="utf-8")
        await harness.aclose()
        await provider.aclose()
    return 0


def _pi_tools(node_executable: str) -> dict[str, Any]:
    completed = subprocess.run(
        [node_executable, "/opt/thinharness-terminal-bench-subscription/pi_subscription_probe.mjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _parse_pi_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    assistant_messages: list[dict[str, Any]] = []
    tool_starts: list[dict[str, Any]] = []
    tool_ends: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") == "message_end" and isinstance(event.get("message"), dict) and event["message"].get("role") == "assistant":
            assistant_messages.append(event["message"])
        elif event.get("type") == "tool_execution_start":
            tool_starts.append(event)
        elif event.get("type") == "tool_execution_end":
            tool_ends.append(event)
    totals = {"ordinary_input_tokens": 0, "cached_input_tokens": 0, "cache_write_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
    response_models: set[str] = set()
    for message in assistant_messages:
        usage = message.get("usage") or {}
        mapping = {
            "ordinary_input_tokens": "input",
            "cached_input_tokens": "cacheRead",
            "cache_write_tokens": "cacheWrite",
            "output_tokens": "output",
            "reasoning_tokens": "reasoning",
        }
        for target, source in mapping.items():
            value = usage.get(source)
            if isinstance(value, int):
                totals[target] += value
        model = message.get("model")
        if isinstance(model, str):
            response_models.add(model)
    totals["input_tokens"] = totals["ordinary_input_tokens"] + totals["cached_input_tokens"] + totals["cache_write_tokens"]
    return {
        "assistant_messages": assistant_messages,
        "request_count": len(assistant_messages),
        "tool_starts": tool_starts,
        "tool_ends": tool_ends,
        "tool_count": len(tool_starts),
        "tool_call_names": [event.get("toolName") for event in tool_starts],
        "usage": totals,
        "response_models": sorted(response_models),
        "stop_reason": assistant_messages[-1].get("stopReason") if assistant_messages else None,
    }


def _run_pi(args: argparse.Namespace, *, url: str, token: str, mode: str) -> int:
    prompt = _load_prompt(args.prompt)
    instruction = args.instruction.read_text(encoding="utf-8")
    install = json.loads(args.install_provenance.read_text(encoding="utf-8"))
    agent_dir = Path("/opt/pi-subscription-agent")
    agent_dir.mkdir(parents=True, exist_ok=True)
    model_config = {
        "providers": {
            "codex-subscription": {
                "baseUrl": url,
                "api": "openai-responses",
                "apiKey": "$TB_SUBSCRIPTION_GATEWAY_TOKEN",
                "models": [
                    {
                        "id": MODEL,
                        "name": "GPT-5.6 Sol via audited cproxy",
                        "reasoning": True,
                        "input": ["text"],
                        "contextWindow": 272000,
                        "maxTokens": 100000,
                        "thinkingLevelMap": {
                            "off": "none",
                            "minimal": "minimal",
                            "low": "low",
                            "medium": "medium",
                            "high": "high",
                            "xhigh": "xhigh",
                            "max": None,
                        },
                        "samplingParams": {"text": dict(TEXT)},
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                        "compat": {"supportsDeveloperRole": True, "supportsStrictMode": True, "supportsLongCacheRetention": False},
                    }
                ],
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(model_config, indent=2) + "\n", encoding="utf-8")
    (agent_dir / "settings.json").write_text(
        json.dumps({"retry": {"enabled": False, "maxRetries": 0}, "compaction": {"enabled": False}}, indent=2) + "\n", encoding="utf-8"
    )
    pi = "/opt/pi-subscription/node_modules/.bin/pi"
    command = [
        pi,
        "--provider",
        "codex-subscription",
        "--model",
        MODEL,
        "--thinking",
        "xhigh",
        "--system-prompt",
        prompt,
        "--mode",
        "json",
        "--print",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--tools",
        "read,bash,edit,write",
        "--approve",
        "--offline",
        instruction,
    ]
    environment = os.environ.copy()
    environment["PI_CODING_AGENT_DIR"] = str(agent_dir)
    environment["PI_OFFLINE"] = "1"
    environment["TB_SUBSCRIPTION_GATEWAY_TOKEN"] = token
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=1800, check=False)
    elapsed = time.perf_counter() - started
    args.events.write_text(completed.stdout, encoding="utf-8")
    args.stderr.write_text(completed.stderr, encoding="utf-8")
    events: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    parsed = _parse_pi_events(events)
    error = None if completed.returncode == 0 else {"type": "PiProcessError", "message": completed.stderr[-4000:]}
    tool_evidence = _pi_tools(str(install["node_executable"]))
    receipt = {
        "schema_version": 1,
        "kind": "subscription-smoke-cell",
        "cell_id": args.cell_id,
        "harness": "pi",
        "mode": mode,
        "backend": "cproxy-codex-subscription" if mode == "real" else "controlled-fake-cproxy-contract",
        "gateway_base_url": url,
        "direct_openai": False,
        "codex_oauth_in_container": False,
        "model": MODEL,
        "reasoning": REASONING,
        "text": TEXT,
        "prompt_sha256": PROMPT_SHA256,
        "execution": _identity(),
        "install": install,
        "harness_version": install.get("pi_version"),
        "tools": tool_evidence,
        "tool_names": [item["name"] for item in tool_evidence["tools"]],
        "request_count": parsed["request_count"],
        "tool_count": parsed["tool_count"],
        "tool_call_names": parsed["tool_call_names"],
        "tool_execution_starts": parsed["tool_starts"],
        "tool_execution_ends": parsed["tool_ends"],
        "usage": parsed["usage"],
        "response_models": parsed["response_models"],
        "stop_reason": parsed["stop_reason"],
        "assistant_messages": parsed["assistant_messages"],
        "events_path": args.events.name,
        "stderr_path": args.stderr.name,
        "event_count": len(events),
        "agent_seconds": elapsed,
        "process_return_code": completed.returncode,
        "retries": {"provider": 0, "agent": 0},
        "error": error,
        "mismatches": [
            "Pi native filesystem/Bash schemas differ from ThinHarness native plugin schemas; "
            "tool names and workspace authority are matched."
        ],
        "verifier_handoff": {"ready": completed.returncode == 0, "workspace": ROOT},
    }
    _atomic_json(args.receipt, receipt)
    if completed.returncode != 0:
        raise RuntimeError(f"Pi subscription process failed: {completed.stderr[-4000:]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("harness", choices=("pi", "thinharness"))
    parser.add_argument("--cell-id", required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--instruction", type=Path, required=True)
    parser.add_argument("--install-provenance", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    url, token, mode = _gateway()
    if args.harness == "thinharness":
        return asyncio.run(_run_thinharness(args, url=url, token=token, mode=mode))
    return _run_pi(args, url=url, token=token, mode=mode)


if __name__ == "__main__":
    raise SystemExit(main())
