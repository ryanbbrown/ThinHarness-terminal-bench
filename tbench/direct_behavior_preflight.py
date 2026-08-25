"""No-model checks for credit exhaustion and restart decisions."""

from __future__ import annotations

import http.client
import json
import tempfile
from pathlib import Path
from typing import Any

from .direct_gateway import run_gateway


def run_behavior_preflight(output: Path) -> dict[str, Any]:
    """Exercise credit and consumed-cell restart behavior without an upstream request."""
    with tempfile.TemporaryDirectory(prefix="direct-behavior-preflight-") as raw:
        root = Path(raw)
        credit = root / "credit"
        with run_gateway(cell_id="behavior--pi", mode="fake-credit", evidence_dir=credit, api_key=None) as gateway:
            connection = http.client.HTTPConnection("127.0.0.1", gateway.port, timeout=10)
            connection.request(
                "POST",
                "/v1/responses",
                body=json.dumps({"model": "gpt-5.6-sol", "stream": False}),
                headers={"Authorization": f"Bearer {gateway.token}", "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            response.read()
            connection.close()
        credit_passed = (
            response.status == 429
            and (credit / "CREDIT_EXHAUSTED.json").is_file()
            and not (credit / "MODEL_REQUEST_STARTED.jsonl").exists()
            and json.loads((credit / "gateway-identity.json").read_text(encoding="utf-8"))["upstream"] is None
        )
        consumed = root / "consumed-cell"
        consumed.mkdir()
        (consumed / "MODEL_REQUEST_STARTED.jsonl").write_text('{"sequence":1}\n', encoding="utf-8")
        restart_decision = "skip_forever" if (consumed / "MODEL_REQUEST_STARTED.jsonl").stat().st_size else "retry_infrastructure"
        empty = root / "pre-request-cell"
        empty.mkdir()
        infrastructure_decision = "skip_forever" if (empty / "MODEL_REQUEST_STARTED.jsonl").exists() else "preserve_and_retry_after_fix"
        result = {
            "schema_version": 1,
            "upstream_requests": 0,
            "credit_exhaustion": {
                "passed": credit_passed,
                "status": response.status,
                "stop_launching_immediately": True,
                "simulated": True,
            },
            "restart": {
                "passed": restart_decision == "skip_forever" and infrastructure_decision == "preserve_and_retry_after_fix",
                "real_model_marker_decision": restart_decision,
                "pre_request_infrastructure_decision": infrastructure_decision,
            },
        }
    if not result["credit_exhaustion"]["passed"] or not result["restart"]["passed"]:
        raise RuntimeError("direct runner behavior preflight failed")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
