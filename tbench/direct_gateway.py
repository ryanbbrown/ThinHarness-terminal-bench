"""Authenticated one-cell gateway for the direct OpenAI Responses API."""

from __future__ import annotations

import hashlib
import http.client
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

from .direct_constants import MODEL, PRICES, UPSTREAM_URL


class DirectGatewayError(RuntimeError):
    """The direct gateway cannot prove or serve its configured route."""


@dataclass(frozen=True)
class GatewayIdentity:
    """The non-secret route identity passed to the launcher."""

    base_url: str
    token: str
    port: int
    cell_id: str
    mode: str
    upstream: str
    benchmark_id: str


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


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


class GatewayState:
    """One direct API credential plus complete non-secret evidence for one cell."""

    def __init__(
        self,
        *,
        cell_id: str,
        mode: str,
        token: str,
        api_key: str | None,
        evidence_dir: Path,
        benchmark_id: str,
        budget_control: Any | None,
    ) -> None:
        self.cell_id = cell_id
        self.mode = mode
        self.token = token
        self.api_key = api_key
        self.evidence_dir = evidence_dir
        self.benchmark_id = benchmark_id
        self.budget_control = budget_control
        self.lock = threading.Lock()
        self.request_count = 0
        self.upstream_request_count = 0
        self.fake_request_count = 0

    def prepare_and_forward(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        incoming_stream = body.get("stream") is True
        nonstreaming = dict(body)
        nonstreaming["stream"] = False
        started = time.monotonic()
        if self.mode == "fake":
            status, response, response_headers = 200, self._fake_response(), {}
        elif self.mode == "fake-credit":
            status = 429
            response = {
                "error": {
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                    "message": "controlled credit-exhaustion preflight",
                }
            }
            response_headers = {}
            _atomic_json(
                self.evidence_dir / "CREDIT_EXHAUSTED.json",
                {"schema_version": 1, "simulated": True, "cell_id": self.cell_id, "status": status, "error_code": "insufficient_quota"},
            )
        else:
            status, response, response_headers = self._direct_request(nonstreaming)
        elapsed = time.monotonic() - started
        if status == 200:
            try:
                _validate_response(response)
                usage = _usage(response)
                if self.budget_control is not None:
                    self.budget_control.settle_usage(self.cell_id, usage)
            except Exception as exc:
                _atomic_json(
                    self.evidence_dir / "FAIL_CLOSED.json",
                    {
                        "schema_version": 1,
                        "benchmark_id": self.benchmark_id,
                        "cell_id": self.cell_id,
                        "reason": str(exc),
                        "type": type(exc).__name__,
                    },
                )
                if self.budget_control is not None:
                    self.budget_control.fail(self.cell_id, str(exc))
                raise
        credit_exhausted = _is_credit_exhaustion(status, response)
        if credit_exhausted and self.mode == "real":
            raw_error = response.get("error")
            error: dict[str, Any] = raw_error if isinstance(raw_error, dict) else {}
            _atomic_json(
                self.evidence_dir / "CREDIT_EXHAUSTED.json",
                {
                    "schema_version": 1,
                    "simulated": False,
                    "cell_id": self.cell_id,
                    "status": status,
                    "error_type": error.get("type"),
                    "error_code": error.get("code"),
                    "message": error.get("message"),
                },
            )
            if self.budget_control is not None:
                self.budget_control.fail(self.cell_id, "provider billing or quota exhaustion")
        with self.lock:
            self.request_count += 1
            sequence = self.request_count
        record = {
            "schema_version": 1,
            "benchmark_id": self.benchmark_id,
            "cell_id": self.cell_id,
            "sequence": sequence,
            "mode": self.mode,
            "route": "direct-openai" if self.mode == "real" else "controlled-fake-direct-openai-contract",
            "upstream": UPSTREAM_URL if self.mode == "real" else None,
            "incoming_stream": incoming_stream,
            "request_sha256": _json_sha256(body),
            "request_bytes": len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()),
            "request": body,
            "status": status,
            "duration_seconds": elapsed,
            "response_sha256": _json_sha256(response),
            "response": response,
            "response_headers": response_headers,
            "response_model": response.get("model"),
            "usage": _usage(response) if status == 200 else None,
            "cost_usd": _cost(response) if status == 200 else None,
            "credit_exhausted": credit_exhausted,
        }
        _append_jsonl(self.evidence_dir / "gateway-audit.jsonl", record)
        return status, response

    def _direct_request(self, body: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
        if not self.api_key:
            raise DirectGatewayError("direct OpenAI credential is absent")
        if self.budget_control is not None:
            self.budget_control.authorize_request(self.cell_id)
        with self.lock:
            self.upstream_request_count += 1
            sequence = self.upstream_request_count
            _append_jsonl(
                self.evidence_dir / "MODEL_REQUEST_STARTED.jsonl",
                {
                    "schema_version": 1,
                    "benchmark_id": self.benchmark_id,
                    "cell_id": self.cell_id,
                    "sequence": sequence,
                    "started_at": time.time(),
                    "payload_sha256": _json_sha256(body),
                    "upstream": UPSTREAM_URL,
                    "transport_retries": 0,
                },
            )
        if self.budget_control is not None:
            self.budget_control.request_started(self.cell_id)
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        connection = http.client.HTTPSConnection("api.openai.com", 443, timeout=1800)
        try:
            connection.request(
                "POST",
                "/v1/responses",
                body=encoded,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": f"thin-harness-terminal-bench/{self.benchmark_id}",
                },
            )
            upstream = connection.getresponse()
            raw = upstream.read()
            status = upstream.status
            headers = {
                key.lower(): value
                for key, value in upstream.getheaders()
                if key.lower()
                in {
                    "x-request-id",
                    "openai-processing-ms",
                    "openai-version",
                    "x-ratelimit-limit-requests",
                    "x-ratelimit-remaining-requests",
                    "x-ratelimit-reset-requests",
                    "x-ratelimit-limit-tokens",
                    "x-ratelimit-remaining-tokens",
                    "x-ratelimit-reset-tokens",
                }
            }
        finally:
            connection.close()
        try:
            response = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DirectGatewayError(f"OpenAI returned non-JSON status {status}") from exc
        if not isinstance(response, dict):
            raise DirectGatewayError("OpenAI response is not an object")
        return status, response, headers

    def _fake_response(self) -> dict[str, Any]:
        with self.lock:
            self.fake_request_count += 1
            sequence = self.fake_request_count
        if sequence == 1:
            command = (
                "set -eu; if printenv OPENAI_API_KEY >/dev/null 2>&1; then exit 41; fi; "
                "printf 'direct OpenAI key is absent from native Bash\\n'"
            )
            arguments: dict[str, Any] = {"command": command}
            if not self.cell_id.endswith("--pi"):
                arguments["cwd"] = "/app"
            output = [
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
                    "content": [{"type": "output_text", "text": "Controlled direct-OpenAI preflight complete.", "annotations": []}],
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


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, state: GatewayState) -> None:
        self.gateway_state = state
        super().__init__(("0.0.0.0", 0), GatewayHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])


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
        state = self.gateway.gateway_state
        self._json(200, {"ok": True, "cell_id": state.cell_id, "mode": state.mode, "upstream": UPSTREAM_URL})

    def do_POST(self) -> None:
        state = self.gateway.gateway_state
        if urlsplit(self.path).path.rstrip("/") != "/v1/responses":
            self._json(404, {"error": {"type": "gateway_error", "message": "unsupported path"}})
            return
        if self.headers.get("Authorization") != f"Bearer {state.token}":
            self._json(401, {"error": {"type": "gateway_auth_error", "message": "invalid ephemeral bearer"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("request is not an object")
            status, response = state.prepare_and_forward(body)
        except Exception as exc:
            self._json(502, {"error": {"type": type(exc).__name__, "message": str(exc)}})
            return
        if body.get("stream") is True and status == 200:
            self._sse(response)
        else:
            self._json(status, response)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload).encode()
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
        encoded = content.encode()
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
    evidence_dir: Path,
    api_key: str | None,
    benchmark_id: str = "direct-openai-20task-pairwise",
    budget_control: Any | None = None,
) -> Iterator[GatewayIdentity]:
    """Run an authenticated gateway for one cell without persisting its credentials."""
    if mode not in {"fake", "real", "fake-credit"}:
        raise ValueError("gateway mode must be fake, fake-credit, or real")
    if mode == "real" and (not api_key or len(api_key) < 20):
        raise DirectGatewayError("OPENAI_API_KEY is absent or invalid")
    token = secrets.token_urlsafe(32)
    state = GatewayState(
        cell_id=cell_id,
        mode=mode,
        token=token,
        api_key=api_key,
        evidence_dir=evidence_dir,
        benchmark_id=benchmark_id,
        budget_control=budget_control,
    )
    server = GatewayServer(state)
    thread = threading.Thread(target=server.serve_forever, name=f"direct-gateway-{cell_id}", daemon=True)
    thread.start()
    identity = {
        "schema_version": 1,
        "benchmark_id": benchmark_id,
        "cell_id": cell_id,
        "mode": mode,
        "bind": "0.0.0.0",
        "port": server.port,
        "container_base_url": f"http://host.docker.internal:{server.port}/v1",
        "provider": "OpenAI" if mode == "real" else "controlled fake",
        "upstream": UPSTREAM_URL if mode == "real" else None,
        "direct_openai": mode == "real",
        "bridge": None,
        "downstream_auth": "ephemeral-random-bearer",
        "downstream_token_persisted": False,
        "openai_key_source": "Doppler launcher environment" if mode == "real" else "none",
        "openai_key_persisted": False,
        "request_retries": 0,
        "transport_retries": 0,
    }
    _atomic_json(evidence_dir / "gateway-identity.json", identity)
    try:
        yield GatewayIdentity(
            base_url=identity["container_base_url"],
            token=token,
            port=server.port,
            cell_id=cell_id,
            mode=mode,
            upstream=UPSTREAM_URL,
            benchmark_id=benchmark_id,
        )
    finally:
        state.api_key = None
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    input_tokens = usage.get("input_tokens")
    cached = input_details.get("cached_tokens")
    cache_write = input_details.get("cache_write_tokens", 0)
    output = usage.get("output_tokens")
    reasoning = output_details.get("reasoning_tokens")
    values = (input_tokens, cached, cache_write, output, reasoning)
    if not all(isinstance(item, int) and item >= 0 for item in values):
        raise DirectGatewayError("OpenAI response usage is incomplete")
    complete = cast(tuple[int, int, int, int, int], values)
    input_count, cached_count, cache_write_count, output_count, reasoning_count = complete
    ordinary = input_count - cached_count - cache_write_count
    if ordinary < 0:
        raise DirectGatewayError("OpenAI input token details are inconsistent")
    return {
        "input_tokens": input_count,
        "ordinary_input_tokens": ordinary,
        "cached_input_tokens": cached_count,
        "cache_write_tokens": cache_write_count,
        "output_tokens": output_count,
        "reasoning_tokens": reasoning_count,
    }


def _cost(response: dict[str, Any]) -> dict[str, Any]:
    usage = _usage(response)
    components = {
        "ordinary_input": usage["ordinary_input_tokens"] * PRICES["ordinary_input"] / 1_000_000,
        "cached_input": usage["cached_input_tokens"] * PRICES["cached_input"] / 1_000_000,
        "cache_write": usage["cache_write_tokens"] * PRICES["cache_write"] / 1_000_000,
        "output": usage["output_tokens"] * PRICES["output"] / 1_000_000,
    }
    return {
        "currency": "USD",
        "components": components,
        "api_equivalent_total": sum(components.values()),
        "actual_cash": (response.get("usage") or {}).get("cost_usd"),
    }


def _validate_response(response: dict[str, Any]) -> None:
    if response.get("model") != MODEL:
        raise DirectGatewayError(f"OpenAI returned unexpected model identity: {response.get('model')!r}")
    _usage(response)


def _is_credit_exhaustion(status: int, response: dict[str, Any]) -> bool:
    error = response.get("error")
    if not isinstance(error, dict):
        return status == 402
    values = {str(error.get(name, "")).lower() for name in ("type", "code")}
    codes = {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active", "credits_exhausted", "usage_limit_reached"}
    return status == 402 or bool(values & codes)


def _fake_usage(input_tokens: int, cached_tokens: int, output_tokens: int, reasoning_tokens: int) -> dict[str, Any]:
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached_tokens, "cache_write_tokens": 0},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        "total_tokens": input_tokens + output_tokens,
    }


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
