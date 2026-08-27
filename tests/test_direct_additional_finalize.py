from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tbench import direct_additional_finalize as finalizer
from tbench.direct_additional_constants import BENCHMARK_ID


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _attempt_fixture() -> tuple[list[dict], list[dict], dict, list[dict]]:
    markers = [{"sequence": sequence} for sequence in range(1, 42)]
    audit = [{"sequence": sequence} for sequence in range(1, 42)]
    receipt = {"request_count": 42}
    events = []
    for attempt in range(1, 43):
        events.append({"type": "turn_start", "attempt": attempt})
        message = {"stopReason": "stop"}
        if attempt == 42:
            message = {"stopReason": "error", "errorMessage": finalizer.LOCAL_DENIAL_ERROR}
        events.append({"type": "turn_end", "attempt": attempt, "message": message})
    return markers, audit, receipt, events


def test_cap_stop_transaction_preserves_block_and_records_before_after_hashes(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    blocked = {"cell_id": finalizer.CAP_CELL, "reason": finalizer.CAP_REASON, "at": 123.0}
    ledger = {
        "active_cell": finalizer.CAP_CELL,
        "blocked": blocked,
        "cells": {finalizer.CAP_CELL: {"status": "consumed"}},
    }
    progress = {"cells": [], "status": "fail_closed", "budget": ledger}
    outcome = {"status": "fail_closed", "checkpointed_cells": 18}
    checkpoint = {"cell_id": finalizer.CAP_CELL, "timing": {"launcher_finished_at": 456.0}}
    for name, value in (("budget-ledger.json", ledger), ("progress.json", progress), ("OUTCOME.json", outcome)):
        _write_json(root / name, value)
    evidence = root / "evidence.txt"
    evidence.write_text("preserved\n", encoding="utf-8")
    initial = finalizer.InitialState(
        progress=progress,
        ledger=ledger,
        outcome=outcome,
        checkpoint=checkpoint,
        immutable_evidence={str(evidence): hashlib.sha256(evidence.read_bytes()).hexdigest()},
    )
    before = finalizer._state_hashes(root)

    receipt = finalizer._commit_cap_stop(root, initial)

    assert receipt["status"] == "completed"
    assert receipt["before_state_sha256"] == before
    assert receipt["after_state_sha256"] == finalizer._state_hashes(root)
    final_ledger = json.loads((root / "budget-ledger.json").read_text(encoding="utf-8"))
    final_progress = json.loads((root / "progress.json").read_text(encoding="utf-8"))
    assert final_ledger["blocked"] == blocked
    assert final_ledger["active_cell"] == finalizer.CAP_CELL
    assert final_ledger["cells"][finalizer.CAP_CELL]["status"] == "cap_exceeded"
    assert final_progress["cells"] == [checkpoint]
    assert final_progress["stop"] == finalizer.FINAL_STOP
    assert finalizer.FINAL_CELL not in final_ledger["cells"]


def test_expected_41_upstream_and_42_native_attempts_are_distinct() -> None:
    markers, audit, receipt, events = _attempt_fixture()

    counts = finalizer._validate_local_attempts(markers, audit, receipt, events)

    assert counts == {
        "native_model_attempt_count": 42,
        "upstream_request_count": 41,
        "request_start_marker_count": 41,
        "locally_denied_attempt_count": 1,
    }
    receipt["request_count"] = 41
    with pytest.raises(finalizer.FinalizationRefused, match="exactly 42 attempts"):
        finalizer._validate_local_attempts(markers, audit, receipt, events)


def test_local_denial_count_mismatch_fails_closed() -> None:
    markers, audit, receipt, events = _attempt_fixture()
    events[-1]["message"] = {"stopReason": "stop"}

    with pytest.raises(finalizer.FinalizationRefused, match="one terminal local cap denial"):
        finalizer._validate_local_attempts(markers, audit, receipt, events)


def test_finalizer_is_outside_frozen_model_facing_identity() -> None:
    progress = json.loads(Path("artifacts/direct-openai-additional-10-pairwise/progress.json").read_text(encoding="utf-8"))

    assert "tbench/direct_additional_finalize.py" not in progress["runner_identity"]["files"]
    assert progress["runner_identity"]["files_sha256"] == finalizer.RUNNER_IDENTITY_SHA256
    assert progress["benchmark_id"] == BENCHMARK_ID
