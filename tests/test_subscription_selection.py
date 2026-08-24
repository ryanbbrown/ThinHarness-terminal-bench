from __future__ import annotations

import json
from pathlib import Path

from tbench.subscription_constants import EXPECTED_CELLS, SELECTION_PATH, TASKS


def test_one_selected_recovery_task_is_low_cost_and_never_prior_launched() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    selected = value["selected"]
    names = [item["task"] for item in selected]
    assert names == list(TASKS) == ["crack-7z-hash"]
    assert not set(names) & set(value["excluded_prior_paid_or_launched_tasks"])
    assert selected[0]["expert_time_estimate_min"] == 5.0
    assert selected[0]["memory_mb"] <= 4096
    assert selected[0]["agent_timeout_sec"] <= 1800
    assert EXPECTED_CELLS == ("crack-7z-hash--pi", "crack-7z-hash--thinharness")
    assert all(not cell.startswith("crack-7z-hash--") for cell in value["preserved_real_subscription_cells"])


def test_preserved_experiment_absence_is_recorded_not_silently_ignored() -> None:
    value = json.loads(SELECTION_PATH.read_text())
    evidence = value["prior_evidence"]
    assert evidence["preserved_experiment_path_present"] is False
    assert not Path(evidence["preserved_experiment_path_checked"]).exists()
    assert "missing receipt can only add exclusions" in evidence["note"].lower()
