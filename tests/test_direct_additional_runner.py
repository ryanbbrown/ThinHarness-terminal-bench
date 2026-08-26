from __future__ import annotations

import json
import os
import stat
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from tbench import direct_additional_launch
from tbench.direct_additional_constants import BENCHMARK_ID, EXPECTED_CELLS, TASKS
from tbench.direct_budget import BudgetBlocked, DirectBudgetLedger
from tbench.direct_gateway import DirectGatewayError, GatewayState
from tbench.durable import atomic_json


def _ledger(path: Path) -> DirectBudgetLedger:
    return DirectBudgetLedger(path, benchmark_id=BENCHMARK_ID, per_cell_cap=Decimal("3.00"), total_cap=Decimal("60.00"))


def _usage_for_output(tokens: int) -> dict[str, int]:
    return {
        "ordinary_input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": tokens,
    }


def test_frozen_order_is_pi_then_thinharness_for_all_ten_tasks() -> None:
    assert len(TASKS) == 10
    assert len(EXPECTED_CELLS) == 20
    assert list(EXPECTED_CELLS) == [f"{task}--{harness}" for task in TASKS for harness in ("pi", "thinharness")]


def test_request_start_permanently_consumes_a_reserved_cell(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget.json")
    cell_id = EXPECTED_CELLS[0]
    ledger.reserve_cell(cell_id)
    ledger.authorize_request(cell_id)
    ledger.request_started(cell_id)

    restarted = _ledger(tmp_path / "budget.json")
    assert restarted.state["cells"][cell_id]["consumed"] is True
    with pytest.raises(BudgetBlocked, match="already has durable budget state"):
        restarted.reserve_cell(cell_id)


def test_restart_skips_a_complete_consumed_cell_without_launching_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cell_id = EXPECTED_CELLS[0]
    cell = tmp_path / "cells" / cell_id
    cell.mkdir(parents=True)
    (cell / "MODEL_REQUEST_STARTED.jsonl").write_text('{"sequence":1}\n', encoding="utf-8")
    checkpoint = {"cell_id": cell_id, "status": "completed", "real_model_attempted": True, "never_rerun": True}
    atomic_json(cell / "CHECKPOINT.json", checkpoint)
    progress = {"mode": "real", "status": "running", "cells": [], "planned_cells": list(EXPECTED_CELLS)}
    ledger = _ledger(tmp_path / "budget.json")
    ledger.reserve_cell(cell_id)
    ledger.request_started(cell_id)
    ledger.settle_usage(cell_id, _usage_for_output(1))
    monkeypatch.setattr(direct_additional_launch, "_checkpoint_is_complete", lambda root, requested, mode: checkpoint)

    assert direct_additional_launch._recover(tmp_path, progress, cell_id, "real", ledger) == "skip"
    assert progress["cells"] == [checkpoint]
    assert ledger.state["cells"][cell_id]["status"] == "settled"


def test_per_cell_usd_three_cap_blocks_all_later_requests(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget.json")
    cell_id = EXPECTED_CELLS[0]
    ledger.reserve_cell(cell_id)
    ledger.request_started(cell_id)

    assert ledger.settle_usage(cell_id, _usage_for_output(100_000)) == Decimal("3")
    assert ledger.blocked is not None
    with pytest.raises(BudgetBlocked, match="per-cell USD 3.00"):
        ledger.authorize_request(cell_id)


def test_total_usd_sixty_accounting_refuses_the_next_reservation(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget.json")
    for index in range(20):
        cell_id = f"cell-{index}"
        ledger.reserve_cell(cell_id)
        ledger.request_started(cell_id)
        ledger.settle_usage(cell_id, _usage_for_output(96_666))
        ledger.finish_cell(cell_id)

    assert Decimal(ledger.state["total_spent_usd"]) == Decimal("57.999600")
    with pytest.raises(BudgetBlocked, match="total cap"):
        ledger.reserve_cell("cell-20")
    assert ledger.blocked is not None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"model": "gpt-5.6-sol", "usage": {}}, "usage is incomplete"),
        (
            {
                "model": "wrong-model",
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens": 1,
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
            "unexpected model identity",
        ),
    ],
)
def test_missing_usage_or_model_identity_blocks_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict, message: str
) -> None:
    ledger = _ledger(tmp_path / "budget.json")
    cell_id = EXPECTED_CELLS[0]
    ledger.reserve_cell(cell_id)
    state = GatewayState(
        cell_id=cell_id,
        mode="real",
        token="x" * 32,
        api_key="x" * 20,
        evidence_dir=tmp_path,
        benchmark_id=BENCHMARK_ID,
        budget_control=ledger,
    )
    monkeypatch.setattr(state, "_direct_request", lambda body: (200, response, {}))

    with pytest.raises(DirectGatewayError, match=message):
        state.prepare_and_forward({"model": "gpt-5.6-sol"})
    assert ledger.blocked is not None
    assert (tmp_path / "FAIL_CLOSED.json").is_file()


def test_billing_or_quota_failure_blocks_future_cells(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = _ledger(tmp_path / "budget.json")
    cell_id = EXPECTED_CELLS[0]
    ledger.reserve_cell(cell_id)
    state = GatewayState(
        cell_id=cell_id,
        mode="real",
        token="x" * 32,
        api_key="x" * 20,
        evidence_dir=tmp_path,
        benchmark_id=BENCHMARK_ID,
        budget_control=ledger,
    )
    monkeypatch.setattr(
        state,
        "_direct_request",
        lambda body: (429, {"error": {"type": "insufficient_quota", "code": "insufficient_quota"}}, {}),
    )

    status, _ = state.prepare_and_forward({"model": "gpt-5.6-sol"})
    assert status == 429
    blocked = ledger.blocked
    assert blocked is not None
    assert blocked["reason"] == "provider billing or quota exhaustion"
    with pytest.raises(BudgetBlocked):
        ledger.reserve_cell(EXPECTED_CELLS[1])


def test_consumed_cell_with_a_missing_receipt_stops_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cell_id = EXPECTED_CELLS[0]
    cell = tmp_path / "cells" / cell_id
    cell.mkdir(parents=True)
    (cell / "MODEL_REQUEST_STARTED.jsonl").write_text('{"sequence":1}\n', encoding="utf-8")
    (cell / "launch.json").write_text(
        json.dumps({"cell_id": cell_id, "task": TASKS[0], "harness": "pi", "mode": "real"}), encoding="utf-8"
    )
    progress = {"mode": "real", "status": "running", "cells": [], "planned_cells": list(EXPECTED_CELLS)}
    ledger = _ledger(tmp_path / "budget.json")
    ledger.reserve_cell(cell_id)
    ledger.request_started(cell_id)
    monkeypatch.setattr(
        direct_additional_launch,
        "_checkpoint_is_complete",
        lambda root, requested, mode: (_ for _ in ()).throw(RuntimeError("native receipt is absent")),
    )

    assert direct_additional_launch._recover(tmp_path, progress, cell_id, "real", ledger) == "blocked"
    assert progress["cells"][0]["status"] == "consumed_interrupted"
    assert ledger.blocked is not None


def test_changed_frozen_hash_stops_before_a_cell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    frozen = repository / "frozen.json"
    frozen.write_text("frozen\n", encoding="utf-8")
    manifest = tmp_path / "hashes.json"
    manifest.write_text(
        json.dumps({"files": {"frozen.json": "0" * 64}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(direct_additional_launch, "PREPARATION_HASHES_PATH", manifest)
    monkeypatch.setattr(direct_additional_launch.direct_launch, "REPOSITORY_ROOT", repository)

    with pytest.raises(RuntimeError, match="frozen preparation hash differs"):
        direct_additional_launch._validate_frozen_inputs(tmp_path / "artifacts")


def test_paid_run_stops_before_source_or_cell_launch_when_preflight_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(direct_additional_launch, "_validate_environment", lambda mode: "x" * 20)
    monkeypatch.setattr(direct_additional_launch, "_validate_frozen_inputs", lambda root: None)
    monkeypatch.setattr(
        direct_additional_launch.direct_additional_validate,
        "validate",
        lambda root, expected_mode: (_ for _ in ()).throw(RuntimeError("preflight receipt is absent")),
    )
    entered_source = False

    def source_bundle():
        nonlocal entered_source
        entered_source = True
        raise AssertionError("source bundle must not be entered")

    monkeypatch.setattr(direct_additional_launch, "_source_bundle", source_bundle)
    with pytest.raises(RuntimeError, match="preflight receipt is absent"):
        direct_additional_launch.run("run")
    assert entered_source is False


def test_paid_launcher_uses_only_the_existing_doppler_secret_boundary(tmp_path: Path) -> None:
    arguments = tmp_path / "doppler-arguments"
    doppler = tmp_path / "doppler"
    doppler.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$ARGUMENTS\"\ntest -z \"${OPENAI_API_KEY:-}\"\n", encoding="utf-8")
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
        ["scripts/run-direct-openai-additional-10.sh"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    command = arguments.read_text(encoding="utf-8")
    assert "--project api-keys" in command
    assert "--config dev_personal" in command
    assert "--only-secrets OPENAI_API_KEY" in command
    assert "--no-fallback" in command
    assert "tbench.direct_additional_launch run" in command


def test_atomic_json_fsyncs_the_file_and_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    kinds: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        kinds.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    atomic_json(tmp_path / "cells" / "cell" / "CHECKPOINT.json", {"status": "completed"})

    assert any(stat.S_ISREG(mode) for mode in kinds)
    assert any(stat.S_ISDIR(mode) for mode in kinds)
