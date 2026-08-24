from __future__ import annotations

import json
from pathlib import Path

import httpx

from tbench.subscription_constants import CPROXY_COMMIT, MODEL, REASONING, TEXT
from tbench.subscription_gateway import run_gateway


def _payload(*, stream: bool) -> dict[str, object]:
    return {
        "model": MODEL,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "test"}]}],
        "stream": stream,
        "reasoning": REASONING,
        "text": TEXT,
        "tools": [{"type": "function", "name": "bash", "description": "bash", "parameters": {"type": "object"}}],
    }


def test_fake_gateway_proves_json_and_streaming_contract_without_codex(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    identity = tmp_path / "identity.json"
    with run_gateway(
        cell_id="fix-git--pi", mode="fake", audit_path=audit, identity_path=identity, auth_path=tmp_path / "absent"
    ) as gateway:
        host_url = gateway.base_url.replace("host.docker.internal", "127.0.0.1")
        unauthorized = httpx.post(f"{host_url}/responses", json=_payload(stream=False))
        assert unauthorized.status_code == 401
        headers = {"Authorization": f"Bearer {gateway.token}"}
        streamed = httpx.post(f"{host_url}/responses", headers=headers, json=_payload(stream=True))
        assert streamed.status_code == 200
        assert "response.output_item.done" in streamed.text
        assert "response.completed" in streamed.text
        completed = httpx.post(f"{host_url}/responses", headers=headers, json=_payload(stream=False))
        assert completed.status_code == 200
        assert completed.json()["model"] == MODEL
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["incoming_stream"] is True
    assert records[1]["incoming_stream"] is False
    assert all(record["response_model"] == MODEL for record in records)
    gateway_identity = json.loads(identity.read_text())
    assert gateway_identity["cproxy"]["commit"] == CPROXY_COMMIT
    assert gateway_identity["codex_auth"]["validated"] is False
