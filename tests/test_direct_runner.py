from __future__ import annotations

import http.client
import json
import os
import subprocess
from pathlib import Path

from tbench import direct_launch
from tbench.direct_constants import EXPECTED_CELLS, TASKS
from tbench.direct_gateway import run_gateway


def _post(port: int, token: str) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(
        "POST",
        "/v1/responses",
        body=json.dumps({"model": "gpt-5.6-sol", "stream": False}),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    response = connection.getresponse()
    value = json.loads(response.read())
    connection.close()
    return response.status, value


def test_selection_freezes_exactly_twenty_fresh_pairs() -> None:
    selection = json.loads(Path("configs/direct-openai-20task-selection.json").read_text())
    proof = json.loads(Path("configs/direct-openai-exclusion-proof.json").read_text())

    assert len(TASKS) == 20
    assert len(EXPECTED_CELLS) == 40
    assert selection["planned_execution_order"] == list(EXPECTED_CELLS)
    assert proof["result"] == "fresh"
    assert not set(TASKS) & set(selection["excluded_prior_selected_or_evidenced_tasks"])


def test_fake_gateway_makes_no_upstream_request_and_records_complete_accounting(tmp_path: Path) -> None:
    with run_gateway(cell_id="cobol-modernization--pi", mode="fake", evidence_dir=tmp_path, api_key=None) as gateway:
        first_status, first = _post(gateway.port, gateway.token)
        second_status, second = _post(gateway.port, gateway.token)

    assert first_status == second_status == 200
    assert first["model"] == second["model"] == "gpt-5.6-sol"
    assert not (tmp_path / "MODEL_REQUEST_STARTED.jsonl").exists()
    audit = [json.loads(line) for line in (tmp_path / "gateway-audit.jsonl").read_text().splitlines()]
    assert [item["sequence"] for item in audit] == [1, 2]
    assert all(item["usage"]["ordinary_input_tokens"] >= 0 for item in audit)
    assert all(item["cost_usd"]["api_equivalent_total"] > 0 for item in audit)


def test_credit_exhaustion_marker_stops_without_upstream_request(tmp_path: Path) -> None:
    with run_gateway(cell_id="cobol-modernization--pi", mode="fake-credit", evidence_dir=tmp_path, api_key=None) as gateway:
        status, response = _post(gateway.port, gateway.token)

    assert status == 429
    assert response["error"]["code"] == "insufficient_quota"
    assert json.loads((tmp_path / "CREDIT_EXHAUSTED.json").read_text())["simulated"] is True
    assert not (tmp_path / "MODEL_REQUEST_STARTED.jsonl").exists()


def test_restart_skips_a_consumed_real_cell_and_preserves_pre_request_attempt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(direct_launch, "RUNS_DIR", tmp_path / "logs")
    consumed_id = EXPECTED_CELLS[0]
    consumed = tmp_path / "cells" / consumed_id
    consumed.mkdir(parents=True)
    (consumed / "MODEL_REQUEST_STARTED.jsonl").write_text('{"sequence":1}\n')
    progress = {"mode": "real", "status": "running", "cells": [], "planned_cells": list(EXPECTED_CELLS)}

    assert direct_launch._recover_interrupted(tmp_path, progress, consumed_id, "real") is True
    assert progress["cells"][0]["status"] == "consumed_interrupted"
    assert json.loads((consumed / "CHECKPOINT.json").read_text())["restart_action"].startswith("never rerun")

    pending_id = EXPECTED_CELLS[1]
    pending = tmp_path / "cells" / pending_id
    pending.mkdir(parents=True)
    (pending / "staging.stderr").write_text("recoverable")
    assert direct_launch._recover_interrupted(tmp_path, progress, pending_id, "real") is False
    assert not pending.exists()
    assert list((tmp_path / "infrastructure-attempts" / pending_id).iterdir())


def test_real_launcher_script_keeps_key_out_of_native_bash_boundary(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    arguments = tmp_path / "doppler-arguments"
    doppler = tmp_path / "doppler"
    doppler.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$ARGUMENTS\"\ntest -z \"${OPENAI_API_KEY:-}\"\n")
    doppler.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment.update(
        {
            "PATH": f"{tmp_path}:{environment['PATH']}",
            "ARGUMENTS": str(arguments),
            "TB_THINHARNESS_LOCAL_SOURCE": str(tmp_path),
        }
    )

    completed = subprocess.run(
        [str(root / "scripts" / "run-direct-openai-20task.sh")],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    command = arguments.read_text()
    assert "--project api-keys" in command
    assert "--config dev_personal" in command
    assert "--only-secrets OPENAI_API_KEY" in command
    assert "python -m tbench.direct_launch run" in command
