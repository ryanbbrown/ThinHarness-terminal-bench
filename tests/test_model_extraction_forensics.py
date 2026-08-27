from __future__ import annotations

from tbench import model_extraction_forensics


def test_redacted_forensic_report_reproduces_from_original_and_v1_raw_evidence() -> None:
    report = model_extraction_forensics.check()

    assert report["scope"]["new_model_calls"] == 0
    assert report["scope"]["evidence_only"] is True
    assert report["classification"].startswith("redacted forensic report")
    assert report["exact_matches_and_differences"]["task_instruction_match"] is True
    assert report["exact_matches_and_differences"]["model_reasoning_text_match"] is True
    assert report["exact_matches_and_differences"]["tool_descriptions_and_schemas_match"] is False
    assert report["exact_matches_and_differences"]["tool_choice_absent_all_requests"] is True
    assert report["exact_matches_and_differences"]["parallel_tool_calls_absent_all_requests"] is True


def test_request_boundaries_state_tool_calls_results_and_policy_requests_are_fingerprinted() -> None:
    report = model_extraction_forensics.build_report()
    pi = report["runs"]["original_pi"]
    original = report["runs"]["original_thinharness"]
    v1 = report["runs"]["v1_thinharness"]

    assert (pi["request_count"], original["request_count"], v1["request_count"]) == (10, 7, 4)
    assert pi["statuses"] == [200] * 10
    assert original["statuses"] == [200] * 6 + [400]
    assert v1["statuses"] == [200] * 3 + [400]
    assert original["initial_request_sha256"] == v1["initial_request_sha256"]
    assert all(row["previous_response_id"]["links_exactly_to_prior_response"] for row in original["requests"][1:])
    assert all(row["previous_response_id"]["links_exactly_to_prior_response"] for row in v1["requests"][1:])
    assert all(not row["previous_response_id"]["present"] for row in pi["requests"])
    assert any(row["response_tool_calls"] for row in pi["requests"])
    assert any(item["kind"] == "function_call_output" for row in original["requests"] for item in row["input"])
    assert report["policy_requests"]["original_thinharness"]["audited_downstream_request_sha256"] == (
        "386d47b7fce9e5c227cd3ca26c90982b7953bf4188a92f78339566042e7e0acd"
    )
    assert report["policy_requests"]["v1_thinharness"]["audited_downstream_request_sha256"] == (
        "2733a25c3559f15e964f56301f6dc1f69373161e56d0e6444df62551dee92e08"
    )
    assert report["policy_requests"]["shared_redacted_response_sha256"] == (
        "254e1738341b44af7678c8b438b4575b73f8d0022b41f36383ae3ac364e3ef95"
    )


def test_forensic_diagnosis_is_bounded_by_the_preserved_comparison() -> None:
    findings = model_extraction_forensics.build_report()["findings"]

    assert findings["task_content"]["supported_as_sole_cause"] is False
    assert findings["prompt_and_tool_packaging"]["different"] is True
    assert findings["intermediate_behavior"]["supported_as_proximate_cause"] is True
    assert findings["intermediate_behavior"]["confidence"] == "medium"
    assert findings["policy_variance"]["ruled_out"] is False
    assert findings["confidence"] == "medium"
    assert len(findings["uncertainties"]) == 4
