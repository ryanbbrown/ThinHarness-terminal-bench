from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tbench import direct_launch, direct_validate
from tbench.direct_constants import EXPECTED_CELLS, TASKS, THINHARNESS_COMMIT
from tbench.direct_gateway import run_gateway
from tbench.source_bundle import EXACT_BUNDLE_REF, ExactCommitBundle


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
    (consumed / "launch.json").write_text(
        json.dumps({"cell_id": consumed_id, "task": consumed_id.rsplit("--", 1)[0], "harness": "pi", "mode": "real"})
    )
    progress = {"mode": "real", "status": "running", "cells": [], "planned_cells": list(EXPECTED_CELLS)}

    assert direct_launch._recover_interrupted(tmp_path, progress, consumed_id, "real") is True
    assert progress["cells"][0]["status"] == "consumed_interrupted"
    assert progress["cells"][0]["never_rerun"] is True
    assert json.loads((consumed / "CHECKPOINT.json").read_text())["restart_action"].startswith("never rerun")

    pending_id = EXPECTED_CELLS[1]
    pending = tmp_path / "cells" / pending_id
    pending.mkdir(parents=True)
    (pending / "staging.stderr").write_text("recoverable")
    assert direct_launch._recover_interrupted(tmp_path, progress, pending_id, "real") is False
    assert not pending.exists()
    assert list((tmp_path / "infrastructure-attempts" / pending_id).iterdir())


def _test_bundle(tmp_path: Path, *, sha256: str, commit: str = "a" * 40, source_head: str = "b" * 40) -> ExactCommitBundle:
    return ExactCommitBundle(
        path=tmp_path / "source.bundle",
        sha256=sha256,
        source_head=source_head,
        target_commit=commit,
        target_tree="c" * 40,
        target_commit_sha256="d" * 64,
        advertised_ref=EXACT_BUNDLE_REF,
        source_head_excluded=True,
    )


def test_restart_accepts_a_same_source_bundle_with_different_transient_bytes(tmp_path: Path) -> None:
    identity = {"files_sha256": "1" * 64, "files": {}}
    original = _test_bundle(tmp_path, sha256="2" * 64)
    progress = direct_launch._load_or_create_progress(tmp_path, "real", identity, original)
    direct_launch._write_progress(tmp_path, progress)

    regenerated = _test_bundle(tmp_path, sha256="3" * 64)
    resumed = direct_launch._load_or_create_progress(tmp_path, "real", identity, regenerated)

    assert resumed["source_bundle_sha256"] == original.sha256
    assert resumed["source_identity"] == direct_launch._source_identity(regenerated)


def test_restart_rejects_a_different_commit_or_source(tmp_path: Path) -> None:
    identity = {"files_sha256": "1" * 64, "files": {}}
    original = _test_bundle(tmp_path, sha256="2" * 64)
    progress = direct_launch._load_or_create_progress(tmp_path, "real", identity, original)
    direct_launch._write_progress(tmp_path, progress)

    different_commit = _test_bundle(tmp_path, sha256="3" * 64, commit="e" * 40)
    with pytest.raises(RuntimeError, match="canonical source identity"):
        direct_launch._load_or_create_progress(tmp_path, "real", identity, different_commit)

    different_source = _test_bundle(tmp_path, sha256="4" * 64, source_head="f" * 40)
    with pytest.raises(RuntimeError, match="canonical source identity"):
        direct_launch._load_or_create_progress(tmp_path, "real", identity, different_source)


def test_legacy_real_restart_upgrade_appends_the_consumed_checkpoint_without_rerun(tmp_path: Path, monkeypatch) -> None:
    source_root = Path("artifacts/direct-openai-20task-pairwise")
    progress = json.loads((source_root / "progress.json").read_text())
    (tmp_path / "cells").mkdir()
    shutil.copy2(source_root / "progress.json", tmp_path / "progress.json")
    for checkpoint in progress["cells"]:
        cell_id = checkpoint["cell_id"]
        source_cell = source_root / "cells" / cell_id
        target_cell = tmp_path / "cells" / cell_id
        target_cell.mkdir()
        shutil.copy2(source_cell / "MODEL_REQUEST_STARTED.jsonl", target_cell / "MODEL_REQUEST_STARTED.jsonl")
        if cell_id.endswith("--thinharness"):
            shutil.copy2(source_cell / "launch.json", target_cell / "launch.json")
            install = next((source_cell / "job").glob("*/agent/install-provenance.json"))
            target_install = target_cell / install.relative_to(source_cell)
            target_install.parent.mkdir(parents=True)
            shutil.copy2(install, target_install)
    consumed_id = "vulnerable-secret--pi"
    shutil.copytree(source_root / "cells" / consumed_id, tmp_path / "cells" / consumed_id)
    audit_before = (tmp_path / "cells" / consumed_id / "gateway-audit.jsonl").read_bytes()
    monkeypatch.setattr(direct_launch, "RUNS_DIR", tmp_path / "logs")
    bundle = _test_bundle(tmp_path, sha256="9" * 64, commit=THINHARNESS_COMMIT, source_head=THINHARNESS_COMMIT)

    resumed = direct_launch._load_or_create_progress(tmp_path, "real", direct_launch._repository_identity(), bundle)
    assert direct_launch._recover_interrupted(tmp_path, resumed, consumed_id, "real") is True

    assert len(resumed["cells"]) == len(progress["cells"]) + 1
    assert resumed["cells"][-1]["cell_id"] == consumed_id
    assert resumed["cells"][-1]["never_rerun"] is True
    assert (tmp_path / "cells" / consumed_id / "gateway-audit.jsonl").read_bytes() == audit_before
    assert resumed["source_bundle_sha256"] == progress["source_bundle_sha256"]
    assert resumed["source_identity_upgrade"]["prior_transient_bundle_sha256"] == progress["source_bundle_sha256"]


def test_policy_error_is_a_final_consumed_failure_with_complete_evidence() -> None:
    cell = Path("artifacts/direct-openai-20task-pairwise/cells/vulnerable-secret--pi")

    checkpoint = direct_validate.validate_cell(cell, mode="real", cell_id="vulnerable-secret--pi")

    assert checkpoint["status"] == "model_attempt_failed"
    assert checkpoint["never_rerun"] is True
    assert checkpoint["request_count"] == 2
    assert checkpoint["successful_request_count"] == 1
    assert checkpoint["usage"] == {
        "input_tokens": 1173,
        "ordinary_input_tokens": 3,
        "cached_input_tokens": 0,
        "cache_write_tokens": 1170,
        "output_tokens": 55,
        "reasoning_tokens": 9,
    }
    assert checkpoint["cost"]["api_equivalent_total"] == 0.008977500000000001
    assert checkpoint["reward"] == 0.0
    assert checkpoint["verifier_outcome"] == {"rewards": {"reward": 0.0}}
    assert checkpoint["timing"]["native_agent_seconds"] == 11.79096371399919
    failure = checkpoint["model_attempt_failure"]
    assert failure["sequence"] == 2
    assert failure["status"] == 400
    assert failure["credit_exhausted"] is False
    assert failure["response"]["error"]["type"] == "invalid_request"
    assert failure["response"]["error"]["code"] == "cyber_policy"
    assert checkpoint["identities"]["runner"]["files_sha256"] == "b8365355010dd3d81b85e14d07f2f8bced41644be3dc1654a20516e9f3b2bec6"
    assert checkpoint["identities"]["gateway"]["upstream"] == "https://api.openai.com/v1/responses"
    assert checkpoint["identities"]["native_harness"]["harness_version"] == "0.84.2"
    assert checkpoint["identities"]["harbor"]["task_id"]["ref"] == "sha256:d76dfa9e256487c5542905b892156f694137aeef784e1abf3f41e15a8c946eac"
    assert all(checkpoint["traces"].values())


def test_policy_recovery_upgrade_allows_only_attested_recovery_files() -> None:
    root = Path("artifacts/direct-openai-20task-pairwise")
    progress = json.loads((root / "progress.json").read_text())
    old_identity = progress["runner_identity"]
    new_identity = json.loads(json.dumps(old_identity))
    new_identity["files"]["tbench/direct_launch.py"] = "1" * 64
    new_identity["files"]["tbench/direct_validate.py"] = "2" * 64
    new_identity["files"]["tbench/source_bundle.py"] = "3" * 64
    new_identity["files_sha256"] = "4" * 64

    assert direct_launch._is_safe_policy_recovery_upgrade(root, progress, old_identity, new_identity) is True
    new_identity["files"]["tbench/direct_gateway.py"] = "4" * 64
    assert direct_launch._is_safe_policy_recovery_upgrade(root, progress, old_identity, new_identity) is False


def test_restart_recovers_exact_policy_failure_once_then_advances(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(direct_launch, "RUNS_DIR", tmp_path / "logs")
    cell_id = "vulnerable-secret--pi"
    source = Path("artifacts/direct-openai-20task-pairwise/cells") / cell_id
    cell = tmp_path / "cells" / cell_id
    shutil.copytree(source, cell)
    (cell / "CHECKPOINT.json").unlink(missing_ok=True)
    audit_before = (cell / "gateway-audit.jsonl").read_bytes()
    progress = {"mode": "real", "status": "running", "cells": [], "planned_cells": list(EXPECTED_CELLS)}

    assert direct_launch._recover_interrupted(tmp_path, progress, cell_id, "real") is True
    assert [item["cell_id"] for item in progress["cells"]] == [cell_id]
    assert progress["cells"][0]["status"] == "model_attempt_failed"
    assert (cell / "gateway-audit.jsonl").read_bytes() == audit_before
    assert direct_launch._recover_interrupted(tmp_path, progress, cell_id, "real") is True
    assert len(progress["cells"]) == 1
    assert direct_launch._recover_interrupted(tmp_path, progress, "vulnerable-secret--thinharness", "real") is False


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
