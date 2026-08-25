from __future__ import annotations

import json
from pathlib import Path

from tbench.subscription_constants import EXPECTED_CELLS, SELECTION_PATH, TASKS


def test_three_selected_extension_tasks_are_low_cost_and_never_prior_launched() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    selected = value["selected"]
    names = [item["task"] for item in selected]
    assert names == list(TASKS) == ["configure-git-webserver", "pytorch-model-recovery", "constraints-scheduling"]
    assert not set(names) & set(value["excluded_prior_paid_or_launched_tasks"])
    assert len(selected) == len(set(names)) == 3
    assert {item["expert_time_estimate_min"] for item in selected} == {15.0}
    assert all(item["memory_mb"] <= 4096 for item in selected)
    assert all(item["agent_timeout_sec"] <= 1800 for item in selected)
    assert EXPECTED_CELLS == tuple(f"{task}--{harness}" for task in names for harness in ("pi", "thinharness"))
    assert all(not cell.startswith(tuple(f"{task}--" for task in names)) for cell in value["preserved_real_subscription_cells"])


def test_selection_freezes_deterministic_three_of_four_minimum_tier_candidates() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    selected = value["selected"]
    assert [item["task"] for item in selected] == [
        "configure-git-webserver",
        "pytorch-model-recovery",
        "constraints-scheduling",
    ]
    assert value["rejected_same_cost_tier"] == [
        {
            "task": "mteb-retrieve",
            "reason": "fourth after sorting eligible 15-minute tasks by memory, agent timeout, compressed amd64 image bytes, and task name",
        }
    ]
    assert all(len(item["task_toml_sha256"]) == 64 for item in selected)
    assert all(item["amd64_image_digest"].startswith("sha256:") for item in selected)


def test_preserved_experiment_absence_is_recorded_not_silently_ignored() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    evidence = value["freshness_proof"]
    assert evidence["preserved_experiment_path_present"] is False
    assert not Path(evidence["preserved_experiment_path_checked"]).exists()
    assert "missing receipt can only add exclusions" in evidence["note"].lower()
