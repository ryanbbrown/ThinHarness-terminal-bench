from __future__ import annotations

from decimal import Decimal

from tbench import direct_supplement_finalize


def test_paid_refusal_evidence_reproduces_and_doom_remains_unconsumed() -> None:
    paid = direct_supplement_finalize.validate_paid_evidence()

    assert paid["usage"] == direct_supplement_finalize.EXPECTED_USAGE
    assert paid["cost"] == Decimal("0.12462250")
    assert len(paid["audit"]) == 4
    assert [item["status"] for item in paid["audit"]] == [200, 200, 200, 400]
    assert paid["checkpoint"]["never_rerun"] is True
    assert paid["checkpoint"]["reward"] is None
    assert paid["checkpoint"]["verifier_outcome"] is None
    assert not (direct_supplement_finalize.PAID_ROOT / "cells" / direct_supplement_finalize.DOOM_CELL_ID).exists()


def test_direct_comparison_keeps_the_original_frozen_and_uses_honest_denominators() -> None:
    report = direct_supplement_finalize.build_comparison_report()

    assert report["label"] == "supplemental direct-comparison update; original frozen campaign unchanged"
    assert report["denominators"] == {
        "planned_task_pairs": 10,
        "original_verifier_complete_pairs": 8,
        "post_supplement_verifier_complete_pairs": 8,
        "incomplete_pairs": 2,
        "supplemental_authorized_cells": 2,
        "supplemental_consumed_cells": 1,
        "supplemental_verifier_outcomes": 0,
        "supplemental_unconsumed_cells": 1,
        "pair_policy": "include a task only when both cells have verifier outcomes",
    }
    assert report["observed_eight_pair_subset"]["pi_reward_sum"] == "7.0"
    assert report["observed_eight_pair_subset"]["thinharness_reward_sum"] == "7.0"
    assert report["full_ten_pair_score"]["available"] is False
    assert report["full_ten_pair_score"]["missing_tasks"] == [
        "model-extraction-relu-logits",
        "make-doom-for-mips",
    ]


def test_paid_tokens_timing_and_cost_are_exact_and_separate_from_provider_cash() -> None:
    observation = direct_supplement_finalize.build_comparison_report()["supplemental_paid_observation"]

    assert observation["requests"] == 4
    assert observation["successful_requests"] == 3
    assert observation["usage"] == {
        "input_tokens": 6625,
        "ordinary_input_tokens": 9,
        "cached_input_tokens": 3510,
        "cache_write_tokens": 3106,
        "output_tokens": 3447,
        "reasoning_tokens": 3168,
    }
    assert observation["cost"]["api_equivalent_usd"] == "0.12462250"
    assert observation["cost"]["provider_reported_actual_cash_usd"] is None
    assert observation["timing"]["launcher_wall_seconds"] == "173.2435368"
    assert observation["timing"]["request_total_seconds"] == "90.5847171250497915"
    assert observation["timing"]["verifier_seconds"] is None
    assert observation["verifier_outcome"] is None
