"""Authenticated, audited cproxy gateway for one sequential Harbor cell."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from cproxy.server import DEFAULT_UPSTREAM_URL, ProxyConfig, ProxyState

from .subscription_constants import CPROXY_COMMIT, CPROXY_VERSION, MODEL


class GatewayError(RuntimeError):
    """The subscription gateway cannot prove or serve its configured route."""


@dataclass(frozen=True)
class GatewayIdentity:
    """Non-secret route identity passed to the launcher and receipts."""

    base_url: str
    token: str
    port: int
    cell_id: str
    mode: str
    cproxy_version: str
    cproxy_commit: str
    upstream: str


class GatewayState:
    """One cproxy state plus complete sanitized request/response audit."""

    def __init__(
        self,
        *,
        cell_id: str,
        mode: str,
        token: str,
        audit_path: Path,
        identity_path: Path,
        auth_path: Path,
        cproxy_state: ProxyState | None,
    ) -> None:
        self.cell_id = cell_id
        self.mode = mode
        self.token = token
        self.audit_path = audit_path
        self.identity_path = identity_path
        self.auth_path = auth_path
        self.cproxy_state = cproxy_state
        self.lock = threading.Lock()
        self.request_count = 0
        self.fake_request_count = 0

    def close(self) -> None:
        if self.cproxy_state is not None:
            self.cproxy_state.close()

    def prepare_and_forward(self, body: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any]]:
        incoming_stream = body.get("stream") is True
        nonstreaming = dict(body)
        nonstreaming["stream"] = False
        started = time.monotonic()
        if self.mode == "fake":
            prepared = _prepare_fake(nonstreaming)
            response = self._fake_response(prepared)
            status = 200
        else:
            if self.cproxy_state is None:
                raise GatewayError("real gateway has no cproxy state")
            prepared = self.cproxy_state.prepare_request(nonstreaming)
            status, response = self.cproxy_state.forward(prepared)
            if status == 200:
                self.cproxy_state.remember_response(prepared, response)
        elapsed = time.monotonic() - started
        if status == 200:
            _validate_response_identity(response)
        audit = self._audit(
            status=status,
            incoming=body,
            prepared=prepared,
            response=response,
            incoming_stream=incoming_stream,
            elapsed=elapsed,
        )
        return status, response, audit

    def _fake_response(self, prepared: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.fake_request_count += 1
            sequence = self.fake_request_count
        if sequence == 1:
            command = (
                "set -eu; "
                "if printenv OPENAI_API_KEY >/dev/null 2>&1; then exit 41; fi; "
                "if test -e /root/.codex/auth.json -o -e /root/.pi/agent/auth.json; then exit 42; fi; "
                "printf 'no reusable model credential in task container\\n'"
            )
            arguments: dict[str, Any] = {"command": command}
            if not self.cell_id.endswith("--pi"):
                arguments["cwd"] = "/app"
            output: list[dict[str, Any]] = [
                {
                    "id": "fc_fake_1",
                    "type": "function_call",
                    "call_id": "call_fake_1",
                    "name": "bash",
                    "arguments": json.dumps(arguments),
                    "status": "completed",
                }
            ]
            usage = _fake_usage(1200, 256, 96, 64)
        else:
            output = [
                {
                    "id": "msg_fake_2",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Controlled no-model preflight complete.", "annotations": []}],
                }
            ]
            usage = _fake_usage(1500, 512, 64, 16)
        return {
            "id": f"resp_fake_{sequence}",
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": MODEL,
            "output": output,
            "usage": usage,
            "error": None,
            "incomplete_details": None,
        }

    def _audit(
        self,
        *,
        status: int,
        incoming: dict[str, Any],
        prepared: dict[str, Any],
        response: dict[str, Any],
        incoming_stream: bool,
        elapsed: float,
    ) -> dict[str, Any]:
        with self.lock:
            self.request_count += 1
            sequence = self.request_count
            record = {
                "schema_version": 1,
                "cell_id": self.cell_id,
                "sequence": sequence,
                "mode": self.mode,
                "route": "cproxy-codex-subscription" if self.mode == "real" else "controlled-fake-cproxy-contract",
                "cproxy": {
                    "version": CPROXY_VERSION,
                    "commit": CPROXY_COMMIT,
                    "upstream": DEFAULT_UPSTREAM_URL,
                },
                "incoming_stream": incoming_stream,
                "request_sha256": _json_sha256(incoming),
                "prepared_request_sha256": _json_sha256(prepared),
                "request": incoming,
                "prepared_request": prepared,
                "status": status,
                "duration_seconds": elapsed,
                "response_sha256": _json_sha256(response),
                "response": response,
                "response_model": response.get("model"),
                "usage": response.get("usage"),
            }
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return record


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: GatewayState) -> None:
        self.gateway_state = state
        super().__init__(("0.0.0.0", 0), GatewayHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def server_close(self) -> None:
        try:
            self.gateway_state.close()
        finally:
            super().server_close()


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def gateway(self) -> GatewayServer:
        return cast(GatewayServer, self.server)

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/health":
            self._json(404, {"error": {"type": "gateway_error", "message": "not found"}})
            return
        self._json(
            200,
            {
                "ok": True,
                "service": "tbench-cproxy-gateway",
                "cell_id": self.gateway.gateway_state.cell_id,
                "mode": self.gateway.gateway_state.mode,
                "cproxy_version": CPROXY_VERSION,
                "cproxy_commit": CPROXY_COMMIT,
                "upstream": DEFAULT_UPSTREAM_URL,
            },
        )

    def do_POST(self) -> None:
        state = self.gateway.gateway_state
        if urlsplit(self.path).path.rstrip("/") != "/v1/responses":
            self._json(404, {"error": {"type": "gateway_error", "message": "unsupported path"}})
            return
        if self.headers.get("Authorization") != f"Bearer {state.token}":
            self._json(401, {"error": {"type": "gateway_auth_error", "message": "invalid ephemeral gateway token"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("request is not an object")
            status, response, _ = state.prepare_and_forward(body)
        except Exception as exc:
            self._json(502, {"error": {"type": type(exc).__name__, "message": str(exc)}})
            return
        if body.get("stream") is True and status == 200:
            self._sse(response)
        else:
            self._json(status, response)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _sse(self, response: dict[str, Any]) -> None:
        events: list[dict[str, Any]] = [{"type": "response.created", "response": {"id": response.get("id"), "status": "in_progress"}}]
        output = response.get("output")
        if isinstance(output, list):
            for index, item in enumerate(output):
                if isinstance(item, dict):
                    events.append({"type": "response.output_item.added", "output_index": index, "item": item})
                    events.append({"type": "response.output_item.done", "output_index": index, "item": item})
        events.append({"type": "response.completed", "response": response})
        content = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events) + "data: [DONE]\n\n"
        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextmanager
def run_gateway(
    *,
    cell_id: str,
    mode: str,
    audit_path: Path,
    identity_path: Path,
    auth_path: Path,
) -> Iterator[GatewayIdentity]:
    """Run one authenticated gateway for exactly one sequential cell."""
    if mode not in {"fake", "real"}:
        raise ValueError("gateway mode must be fake or real")
    if importlib.metadata.version("cproxy") != CPROXY_VERSION:
        raise GatewayError("installed cproxy version differs from the frozen version")
    token = secrets.token_urlsafe(32)
    cproxy_state = None
    config = None
    if mode == "real":
        config = ProxyConfig(
            auth_path=auth_path, upstream_url=DEFAULT_UPSTREAM_URL, max_request_seconds=1800, max_idle_seconds=300, chains_max=100
        )
        cproxy_state = ProxyState(config)
        cproxy_state.validate_auth()
    state = GatewayState(
        cell_id=cell_id,
        mode=mode,
        token=token,
        audit_path=audit_path,
        identity_path=identity_path,
        auth_path=auth_path,
        cproxy_state=cproxy_state,
    )
    server = GatewayServer(state)
    thread = threading.Thread(target=server.serve_forever, name=f"subscription-gateway-{cell_id}", daemon=True)
    thread.start()
    identity = {
        "schema_version": 1,
        "cell_id": cell_id,
        "mode": mode,
        "bind": "0.0.0.0",
        "port": server.port,
        "container_base_url": f"http://host.docker.internal:{server.port}/v1",
        "downstream_auth": "ephemeral-random-bearer",
        "downstream_token_persisted": False,
        "cproxy": {
            "version": CPROXY_VERSION,
            "commit": CPROXY_COMMIT,
            "upstream": DEFAULT_UPSTREAM_URL,
            "config_fingerprint": config.fingerprint if config is not None else None,
            "request_retries": 0,
        },
        "codex_auth": {
            "source": "host Codex CLI auth file" if mode == "real" else "controlled dummy contract",
            "path_persisted": False,
            "validated": mode == "real",
        },
    }
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        yield GatewayIdentity(
            base_url=identity["container_base_url"],
            token=token,
            port=server.port,
            cell_id=cell_id,
            mode=mode,
            cproxy_version=CPROXY_VERSION,
            cproxy_commit=CPROXY_COMMIT,
            upstream=DEFAULT_UPSTREAM_URL,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _prepare_fake(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    result.pop("stream", None)
    result.pop("max_output_tokens", None)
    result.pop("metadata", None)
    result["store"] = False
    return result


def _fake_usage(input_tokens: int, cached_tokens: int, output_tokens: int, reasoning_tokens: int) -> dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached_tokens, "cache_write_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        "total_tokens": input_tokens + output_tokens,
    }


def _validate_response_identity(response: dict[str, Any]) -> None:
    if response.get("model") != MODEL:
        raise GatewayError(f"Codex backend returned unexpected model identity: {response.get('model')!r}")
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise GatewayError("Codex backend response omitted usage")
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    if not isinstance(usage.get("input_tokens"), int) or not isinstance(usage.get("output_tokens"), int):
        raise GatewayError("Codex backend response omitted input/output token counts")
    if not isinstance(input_details, dict) or not isinstance(input_details.get("cached_tokens"), int):
        raise GatewayError("Codex backend response omitted cached token usage")
    if not isinstance(input_details.get("cache_write_tokens"), int):
        raise GatewayError("Codex backend response omitted cache-write token usage")
    if not isinstance(output_details, dict) or not isinstance(output_details.get("reasoning_tokens"), int):
        raise GatewayError("Codex backend response omitted reasoning token usage")


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
