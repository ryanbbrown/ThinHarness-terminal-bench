from __future__ import annotations

from decimal import Decimal

from tbench import direct_supplement_v2_finalize


def test_paid_v2_receipts_requests_verifier_and_hashes_reproduce() -> None:
    paid = direct_supplement_v2_finalize.validate_paid_evidence()

    assert len(paid["audit"]) == 55
    assert len(paid["markers"]) == 55
    assert paid["usage"] == direct_supplement_v2_finalize.EXPECTED_USAGE
    assert paid["cost"] == Decimal("4.85320175")
    assert paid["checkpoint"]["reward"] == 0.0
    assert paid["checkpoint"]["never_rerun"] is True
    assert paid["native"]["tool_count"] == 83
    assert paid["native"]["stop_reason"] == "end_turn"
    assert paid["harbor"]["verifier_result"] == {"rewards": {"reward": 0.0}}
    assert paid["receipt"]["secret_persisted"] is False


def test_v2_comparison_adds_doom_zero_zero_and_leaves_model_extraction_unmatched() -> None:
    report = direct_supplement_v2_finalize.build_comparison_report()

    assert report["status"] == "nine_pairs_complete_one_unmatched_policy_refusal"
    assert report["denominators"] == {
        "planned_task_pairs": 10,
        "original_verifier_complete_pairs": 8,
        "post_v2_verifier_complete_pairs": 9,
        "incomplete_pairs": 1,
        "matched_pair_policy": "include a task when Pi and the compared ThinHarness cell both have verifier outcomes",
        "v1_authorized_cells": 2,
        "v1_consumed_cells": 1,
        "v1_verifier_outcomes": 0,
        "v1_unconsumed_cells": 1,
        "v2_authorized_cells": 1,
        "v2_consumed_cells": 1,
        "v2_verifier_outcomes": 1,
        "v2_unconsumed_cells": 0,
        "remaining_authorized_future_cells": 0,
    }
    assert report["observed_nine_pair_subset"] == {
        "scope": "Descriptive only; model extraction remains unmatched.",
        "denominator": 9,
        "pi_reward_sum": "7.0",
        "thinharness_reward_sum": "7.0",
        "pi_minus_thinharness_reward_sum": "0.0",
    }
    assert report["affected_tasks"]["make-doom-for-mips"]["original_pi_reward"] == 0.0
    assert report["affected_tasks"]["make-doom-for-mips"]["v2_thinharness_reward"] == 0.0
    assert report["affected_tasks"]["make-doom-for-mips"]["pair_included"] is True
    assert report["full_ten_pair_score"]["available"] is False
    assert report["full_ten_pair_score"]["missing_tasks"] == ["model-extraction-relu-logits"]


def test_paid_v2_tokens_cost_cap_and_timing_are_exact() -> None:
    observation = direct_supplement_v2_finalize.build_comparison_report()["v2_paid_observation"]

    assert observation["requests"] == observation["successful_requests"] == 55
    assert observation["tool_calls"] == 83
    assert observation["usage"] == {
        "input_tokens": 6_077_818,
        "ordinary_input_tokens": 165,
        "cached_input_tokens": 5_924_686,
        "cache_write_tokens": 152_967,
        "output_tokens": 31_133,
        "reasoning_tokens": 11_192,
    }
    assert observation["cost"] == {
        "currency": "USD",
        "api_equivalent_usd": "4.85320175",
        "provider_reported_actual_cash_usd": None,
        "components": {
            "ordinary_input": "0.00082500",
            "cached_input": "2.96234300",
            "cache_write": "0.95604375",
            "output": "0.93399000",
        },
        "cap_usd": "10.00",
        "cap_breached": False,
    }
    assert observation["timing"] == {
        "launcher_wall_seconds": "818.1905501",
        "harbor_wall_seconds": "813.994933",
        "environment_setup_seconds": "1.033803",
        "agent_setup_seconds": "14.858077",
        "agent_execution_seconds": "771.261209",
        "native_agent_seconds": "770.4225924339999",
        "request_total_seconds": "520.7819349977653531",
        "verifier_seconds": "15.384506",
    }


def test_old_evidence_and_redacted_forensics_remain_immutable_and_reproducible() -> None:
    report = direct_supplement_v2_finalize.build_comparison_report()

    assert report["evidence"]["original_and_v1_evidence_immutable"] is True
    assert report["evidence"]["original_report_sha256"] == "c0654560fa5733585e3467bc7e0e28369247e49524178ccce21d13d983032310"
    assert report["evidence"]["v1_comparison_report_sha256"] == ("b51d4bf784e2719af2d3b9c3a973102557517053695c0370a4a7ccab82310198")
    assert report["forensic_diagnosis"]["report_sha256"] == ("968499c7ab4893ba490238e2d8b799e0133d535723ad259702fc52fb806ad7b1")
    assert report["forensic_diagnosis"]["confidence"] == "medium"
    assert report["supplemental_costs"] == {
        "v1_api_equivalent_usd": "0.12462250",
        "v2_api_equivalent_usd": "4.85320175",
        "combined_api_equivalent_usd": "4.97782425",
        "provider_reported_actual_cash_usd": None,
    }
