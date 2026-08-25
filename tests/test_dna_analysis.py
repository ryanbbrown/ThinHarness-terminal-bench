from __future__ import annotations

from tbench import dna_analysis


def test_public_dna_prompt_does_not_select_the_hidden_split() -> None:
    report = dna_analysis.build()

    assert report["answer"] == "No"
    assert report["deterministic_public_split"] is False
    assert report["all_sequence_valid_split_indices"] == [213, 214, 215]
    assert report["requested_repeated_ag_endpoint_partitions"] == [213, 215]
    assert [item["public_requirement_met"] for item in report["partitions"]] == [True, True]
    assert [item["hidden_verifier_accepts"] for item in report["partitions"]] == [True, False]
    assert report["partitions"][0]["insert"] == "ag" + report["partitions"][1]["insert"][:-2]


def test_dna_analysis_report_reproduces_from_preserved_evidence() -> None:
    assert dna_analysis.REPORT_PATH.read_text() == dna_analysis.render()
