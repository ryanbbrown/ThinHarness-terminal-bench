from __future__ import annotations

import json
from pathlib import Path

import pytest

from tbench.budget import BudgetError, initialize_ledger, load_ledger, reserve_request, settle_request
from tbench.constants import DATASET_DIGEST, MODEL_ID, TASK_NAME


def initialize(path: Path, *, attempt: float = 0.5, total: float = 1.0, prior: float = 0.0) -> None:
    initialize_ledger(
        path,
        launch_id="test-launch",
        dataset_digest=DATASET_DIGEST,
        task=TASK_NAME,
        model=MODEL_ID,
        attempt_ceiling_usd=attempt,
        implementation_ceiling_usd=total,
        prior_implementation_spend_usd=prior,
    )


def test_reserves_before_network_and_records_every_token_class(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    initialize(path)

    reservation = reserve_request(path, payload_bytes=1_000, payload_sha256="a" * 64)
    before_response = json.loads(path.read_text())

    assert before_response["in_flight_request_id"] == reservation.request_id
    assert before_response["reserved_usd"] <= 0.5
    cost = settle_request(
        path,
        request_id=reservation.request_id,
        response_model=MODEL_ID,
        input_tokens=600,
        ordinary_input_tokens=400,
        cached_input_tokens=200,
        cache_write_tokens=0,
        output_tokens=300,
        reasoning_tokens=250,
        reported_cost_usd=None,
    )
    ledger = load_ledger(path)
    assert cost == pytest.approx(0.0111)
    assert ledger["spent_usd"] == pytest.approx(0.0111)
    assert ledger["in_flight_request_id"] is None
    assert ledger["requests"][0]["usage"] == {
        "input_tokens": 600,
        "ordinary_input_tokens": 400,
        "cached_input_tokens": 200,
        "cache_write_tokens": 0,
        "output_tokens": 300,
        "reasoning_tokens": 250,
    }


def test_missing_or_inconsistent_usage_leaves_reservation_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    initialize(path)
    reservation = reserve_request(path, payload_bytes=100, payload_sha256="b" * 64)

    with pytest.raises(BudgetError, match="do not reconcile"):
        settle_request(
            path,
            request_id=reservation.request_id,
            response_model=MODEL_ID,
            input_tokens=10,
            ordinary_input_tokens=10,
            cached_input_tokens=1,
            cache_write_tokens=0,
            output_tokens=1,
            reasoning_tokens=0,
            reported_cost_usd=None,
        )

    stopped = json.loads(path.read_text())
    assert stopped["in_flight_request_id"] == reservation.request_id
    with pytest.raises(BudgetError, match="already in flight"):
        reserve_request(path, payload_bytes=100, payload_sha256="c" * 64)


def test_wrong_response_identity_leaves_reservation_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    initialize(path)
    reservation = reserve_request(path, payload_bytes=100, payload_sha256="e" * 64)

    with pytest.raises(BudgetError, match="model identity"):
        settle_request(
            path,
            request_id=reservation.request_id,
            response_model="gpt-5.6-sol-imposter",
            input_tokens=10,
            ordinary_input_tokens=10,
            cached_input_tokens=0,
            cache_write_tokens=0,
            output_tokens=1,
            reasoning_tokens=0,
            reported_cost_usd=None,
        )

    assert json.loads(path.read_text())["in_flight_request_id"] == reservation.request_id


def test_prior_spend_reduces_total_authorization(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    initialize(path, attempt=0.5, total=1.0, prior=0.94)

    reservation = reserve_request(path, payload_bytes=100, payload_sha256="d" * 64)

    assert reservation.reserved_usd <= 0.06
    assert reservation.max_output_tokens < 334


def test_corruption_and_orphaned_reservations_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    initialize(path)
    value = json.loads(path.read_text())
    value["reserved_usd"] = 0.1
    path.write_text(json.dumps(value))

    with pytest.raises(BudgetError, match="orphaned reservation"):
        load_ledger(path)
