from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tbench import direct_additional_launch, direct_validate
from tbench import direct_additional_recovery as recovery
from tbench.direct_additional_constants import BENCHMARK_ID, EXPECTED_CELLS


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value, sort_keys=True) + "\n" for value in values), encoding="utf-8")


def _policy_fixture(tmp_path: Path) -> tuple[Path, dict, dict]:
    root = tmp_path / "campaign"
    cell = root / "cells" / recovery.POLICY_CELL
    trial = cell / "job" / "model-extraction-relu-logits__fixture"
    launch = {
        "benchmark_id": BENCHMARK_ID,
        "cell_id": recovery.POLICY_CELL,
        "task": "model-extraction-relu-logits",
        "harness": "thinharness",
        "mode": "real",
        "harbor_exit_code": 0,
        "runner_identity": {"files_sha256": recovery.FROZEN_RUNNER_FILES_SHA256},
    }
    gateway = {
        "benchmark_id": BENCHMARK_ID,
        "cell_id": recovery.POLICY_CELL,
        "mode": "real",
        "provider": "OpenAI",
        "upstream": "https://api.openai.com/v1/responses",
        "direct_openai": True,
        "bridge": None,
        "request_retries": 0,
        "transport_retries": 0,
    }
    aggregate_usage = {
        "input_tokens": 40_024,
        "ordinary_input_tokens": 18,
        "cached_input_tokens": 28_559,
        "cache_write_tokens": 11_447,
        "output_tokens": 9_668,
        "reasoning_tokens": 7_586,
    }
    components = {
        "ordinary_input": 0.00009,
        "cached_input": 0.0142795,
        "cache_write": 0.07154375,
        "output": 0.29004,
    }
    markers = []
    audit = []
    for sequence in range(1, 7):
        usage = aggregate_usage if sequence == 1 else {name: 0 for name in aggregate_usage}
        cost_components = components if sequence == 1 else {name: 0 for name in components}
        cost = 0.37595325 if sequence == 1 else 0
        markers.append(
            {
                "benchmark_id": BENCHMARK_ID,
                "cell_id": recovery.POLICY_CELL,
                "sequence": sequence,
                "payload_sha256": f"{sequence:064x}",
                "upstream": "https://api.openai.com/v1/responses",
                "transport_retries": 0,
            }
        )
        audit.append(
            {
                "benchmark_id": BENCHMARK_ID,
                "cell_id": recovery.POLICY_CELL,
                "sequence": sequence,
                "status": 200,
                "upstream": "https://api.openai.com/v1/responses",
                "request_sha256": f"{sequence + 10:064x}",
                "response_model": "gpt-5.6-sol",
                "response": {"output": []},
                "usage": usage,
                "cost_usd": {"api_equivalent_total": cost, "components": cost_components},
            }
        )
    markers.append(
        {
            "benchmark_id": BENCHMARK_ID,
            "cell_id": recovery.POLICY_CELL,
            "sequence": 7,
            "payload_sha256": f"{7:064x}",
            "upstream": "https://api.openai.com/v1/responses",
            "transport_retries": 0,
        }
    )
    audit.append(
        {
            "benchmark_id": BENCHMARK_ID,
            "cell_id": recovery.POLICY_CELL,
            "sequence": 7,
            "status": 400,
            "upstream": "https://api.openai.com/v1/responses",
            "request_sha256": f"{17:064x}",
            "response_model": None,
            "response": recovery.POLICY_RESPONSE,
            "response_sha256": recovery._canonical_hash(recovery.POLICY_RESPONSE),
            "credit_exhausted": False,
            "usage": None,
            "cost_usd": None,
        }
    )
    _write_json(cell / "launch.json", launch)
    _write_json(cell / "gateway-identity.json", gateway)
    _write_jsonl(cell / "MODEL_REQUEST_STARTED.jsonl", markers)
    _write_jsonl(cell / "gateway-audit.jsonl", audit)
    _write_json(
        trial / "result.json",
        {
            "exception_info": {"exception_message": "provider error: cyber_policy"},
            "verifier": None,
            "verifier_result": None,
        },
    )
    _write_json(
        trial / "agent" / "thinharness-direct-result.json",
        {
            "cell_id": recovery.POLICY_CELL,
            "mode": "real",
            "model": "gpt-5.6-sol",
            "request_count": 6,
            "response_models": ["gpt-5.6-sol"],
        },
    )
    checkpoint = direct_validate.cell_summary(cell, status="model_attempt_failed", real_model_attempted=True)
    _write_json(cell / "CHECKPOINT.json", checkpoint)
    progress = {
        "benchmark_id": BENCHMARK_ID,
        "mode": "real",
        "status": "fail_closed",
        "planned_cells": list(EXPECTED_CELLS),
        "runner_identity": {"files_sha256": recovery.FROZEN_RUNNER_FILES_SHA256},
        "cells": [{"cell_id": cell_id} for cell_id in EXPECTED_CELLS[: recovery.POLICY_INDEX]] + [checkpoint],
        "finished_at": 1.0,
        "stop": {"cell_id": recovery.POLICY_CELL, "reason": "model_attempt_failed"},
    }
    ledger = {
        "benchmark_id": BENCHMARK_ID,
        "per_cell_cap_usd": "3.00",
        "total_cap_usd": "60.00",
        "total_spent_usd": "11.89850475",
        "active_cell": recovery.POLICY_CELL,
        "blocked": {
            "cell_id": recovery.POLICY_CELL,
            "reason": "cell ended without complete receipt: model_attempt_failed",
        },
        "cells": {
            recovery.POLICY_CELL: {
                "consumed": True,
                "status": "consumed",
                "request_count": 7,
                "spent_usd": "0.37595325",
            }
        },
    }
    return root, progress, ledger


def _activation_receipt(root: Path, tmp_path: Path, progress: dict, ledger: dict) -> None:
    evidence = tmp_path / "evidence.bin"
    evidence.write_bytes(b"frozen evidence\n")
    _write_json(root / "progress.json", progress)
    _write_json(root / "budget-ledger.json", ledger)
    _write_json(
        root / recovery.RECEIPT_NAME,
        {
            "schema_version": 1,
            "benchmark_id": BENCHMARK_ID,
            "status": "completed",
            "policy_cell": recovery.POLICY_CELL,
            "frozen_runner_files_sha256": recovery.FROZEN_RUNNER_FILES_SHA256,
            "remaining_cells": list(EXPECTED_CELLS[recovery.POLICY_INDEX + 1 :]),
            "immutable_evidence_sha256": {"evidence.bin": hashlib.sha256(evidence.read_bytes()).hexdigest()},
        },
    )


def test_receipted_policy_refusal_is_consumed_and_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, progress, ledger = _policy_fixture(tmp_path)
    ledger["cells"][recovery.POLICY_CELL]["status"] = "settled"
    ledger["active_cell"] = None
    ledger["blocked"] = None
    _activation_receipt(root, tmp_path, progress, ledger)
    monkeypatch.setattr(recovery, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(recovery, "ARTIFACT_DIR", root)
    monkeypatch.setattr(direct_additional_launch.direct_validate, "validate_cell", recovery.validate_cell_with_recovery)

    assert direct_additional_launch._recover(root, progress, recovery.POLICY_CELL, "real", None) == "skip"
    assert progress["cells"][recovery.POLICY_INDEX]["never_rerun"] is True
    assert len(progress["cells"]) == 16


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("billing", "exact non-credit cyber_policy"),
        ("quota", "exact non-credit cyber_policy"),
        ("credit", "exact non-credit cyber_policy"),
        ("missing_usage", "missing usage"),
    ],
)
def test_billing_quota_credit_or_missing_usage_cannot_resume(
    tmp_path: Path, defect: str, message: str
) -> None:
    root, progress, ledger = _policy_fixture(tmp_path)
    audit_path = root / "cells" / recovery.POLICY_CELL / "gateway-audit.jsonl"
    audit = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    if defect == "billing":
        audit[-1]["response"] = {"error": {"type": "billing_error", "code": "billing_hard_limit"}}
    elif defect == "quota":
        audit[-1]["status"] = 429
        audit[-1]["response"] = {"error": {"type": "insufficient_quota", "code": "insufficient_quota"}}
    elif defect == "credit":
        audit[-1]["credit_exhausted"] = True
    else:
        audit[0]["usage"].pop("output_tokens")
    _write_jsonl(audit_path, audit)

    with pytest.raises(recovery.RecoveryRefused, match=message):
        recovery._validate_policy_cell(root, progress, ledger)


def test_later_consumed_cell_rejects_recovery(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    later = EXPECTED_CELLS[recovery.POLICY_INDEX + 1]
    marker = root / "cells" / later / "MODEL_REQUEST_STARTED.jsonl"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"sequence":1}\n', encoding="utf-8")

    with pytest.raises(recovery.RecoveryRefused, match="later cell is already consumed"):
        recovery._validate_no_later_consumed(root, {"cells": {}})


def test_recovery_atomically_repairs_only_control_state_and_records_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, progress, ledger = _policy_fixture(tmp_path)
    outcome = {
        "benchmark_id": BENCHMARK_ID,
        "mode": "real",
        "status": "fail_closed",
        "checkpointed_cells": 16,
        "planned_cells": 20,
        "stop": progress["stop"],
    }
    immutable_path = tmp_path / "evidence.bin"
    immutable_path.write_bytes(b"frozen evidence\n")
    immutable = {"evidence.bin": hashlib.sha256(immutable_path.read_bytes()).hexdigest()}
    for name, value in zip(recovery._STATE_NAMES, (ledger, progress, outcome), strict=True):
        _write_json(root / name, value)
    audit_path = root / "cells" / recovery.POLICY_CELL / "gateway-audit.jsonl"
    audit_before = audit_path.read_bytes()
    before = recovery._state_hashes(root)
    monkeypatch.setattr(recovery, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        recovery,
        "_validate_initial",
        lambda requested: (copy.deepcopy(progress), copy.deepcopy(ledger), copy.deepcopy(outcome), immutable),
    )

    receipt = recovery.recover(root)

    assert receipt["before_state_sha256"] == before
    assert receipt["after_state_sha256"] == recovery._state_hashes(root)
    assert (root / recovery.RECEIPT_NAME).is_file()
    assert audit_path.read_bytes() == audit_before
    repaired_ledger = json.loads((root / "budget-ledger.json").read_text())
    repaired_progress = json.loads((root / "progress.json").read_text())
    assert repaired_ledger["cells"][recovery.POLICY_CELL]["status"] == "settled"
    assert repaired_ledger["active_cell"] is None and repaired_ledger["blocked"] is None
    assert repaired_progress["status"] == "recovery_ready"
    assert repaired_progress["cells"][recovery.POLICY_INDEX]["status"] == "model_attempt_failed"


def test_frozen_model_facing_runner_identity_hash_is_unchanged() -> None:
    identity = json.loads(
        Path("artifacts/direct-openai-additional-10-pairwise/progress.json").read_text(encoding="utf-8")
    )["runner_identity"]
    actual = {relative: hashlib.sha256(Path(relative).read_bytes()).hexdigest() for relative in identity["files"]}

    assert actual == identity["files"]
    assert recovery._canonical_hash(actual) == identity["files_sha256"] == recovery.FROZEN_RUNNER_FILES_SHA256
    assert "tbench/direct_additional_recovery.py" not in actual
    assert "tbench/__init__.py" not in actual
