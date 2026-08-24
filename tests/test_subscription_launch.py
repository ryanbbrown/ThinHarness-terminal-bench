from __future__ import annotations

import json
from pathlib import Path

import pytest

from tbench import subscription_launch
from tbench.subscription_constants import DATASET_DIGEST, EXPECTED_CELLS, MODEL


def test_harbor_cell_is_single_attempt_single_concurrency_zero_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subscription_launch.shutil, "which", lambda _: "/venv/bin/harbor")
    command = subscription_launch._harbor_command(
        cell_id="raman-fitting--pi", task="raman-fitting", harness="pi", mode="fake", job_name="job"
    )
    assert command[command.index("--dataset") + 1].endswith(f"@{DATASET_DIGEST}")
    assert command[command.index("--model") + 1] == f"openai/{MODEL}"
    assert command[command.index("--n-attempts") + 1] == "1"
    assert command[command.index("--n-concurrent") + 1] == "1"
    assert command[command.index("--n-concurrent-agents") + 1] == "1"
    assert command[command.index("--max-retries") + 1] == "0"
    assert "--upload" not in command and "--public" not in command
    assert not any("token" in item.lower() or "auth.json" in item for item in command)


def test_api_credentials_are_rejected_before_fake_or_real_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "forbidden")
    with pytest.raises(RuntimeError, match="API credential environment is forbidden"):
        subscription_launch._validate_environment("fake")


def test_expected_cells_are_exactly_four_matched_pairs() -> None:
    assert len(EXPECTED_CELLS) == 8
    assert {cell.rsplit("--", 1)[1] for cell in EXPECTED_CELLS} == {"pi", "thinharness"}
    assert all(
        sum(cell.startswith(task + "--") for cell in EXPECTED_CELLS) == 2
        for task in ("raman-fitting", "fix-git", "prove-plus-comm", "crack-7z-hash")
    )


def test_cproxy_lock_pins_exact_commit() -> None:
    root = Path(__file__).resolve().parent.parent
    lock = (root / "uv.lock").read_text()
    assert "cproxy.git?rev=ef96cbaea614753171627c059297e163fed0bc53" in lock
    assert "ef96cbaea614753171627c059297e163fed0bc53" in lock


def test_pi_lock_pins_exact_package_and_integrity() -> None:
    root = Path(__file__).resolve().parent.parent
    lock = json.loads((root / "configs" / "pi-subscription-package-lock.json").read_text())
    package = lock["packages"]["node_modules/@earendil-works/pi-coding-agent"]
    assert package["version"] == "0.84.2"
    assert package["integrity"].startswith("sha512-")
