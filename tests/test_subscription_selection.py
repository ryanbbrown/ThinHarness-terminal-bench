from __future__ import annotations

import json
from pathlib import Path

from tbench.subscription_constants import EXPECTED_CELLS, SELECTION_PATH, TASKS


def test_four_selected_tasks_are_low_cost_unique_and_never_prior_paid() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    selected = value["selected"]
    names = [item["task"] for item in selected]
    assert set(names) == set(TASKS)
    assert len(names) == len(set(names)) == 4
    assert not set(names) & set(value["excluded_prior_paid_or_launched_tasks"])
    assert all(item["expert_time_estimate_min"] == 5.0 for item in selected)
    assert all(item["memory_mb"] <= 4096 for item in selected)
    assert all(item["agent_timeout_sec"] <= 1800 for item in selected)
    assert len(EXPECTED_CELLS) == 8


def test_preserved_experiment_absence_is_recorded_not_silently_ignored() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    evidence = value["prior_evidence"]
    assert evidence["preserved_experiment_path_present"] is False
    assert not Path(evidence["preserved_experiment_path_checked"]).exists()
    assert "missing receipt can only add exclusions" in evidence["note"].lower()
