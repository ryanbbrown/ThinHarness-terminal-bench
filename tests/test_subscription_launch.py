from __future__ import annotations

import json
import subprocess
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


def test_bundle_preview_accepts_later_clean_head_and_stages_only_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.com"], check=True)
    (source / "source.py").write_text("pin = True\n")
    subprocess.run(["git", "-C", str(source), "add", "source.py"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "pin"], check=True)
    target = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    (source / "source.py").write_text("pin = True\nlater = True\n")
    subprocess.run(["git", "-C", str(source), "commit", "-qam", "later"], check=True)
    later = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.setenv("TB_THINHARNESS_LOCAL_SOURCE", str(source))
    monkeypatch.setattr(subscription_launch, "THINHARNESS_COMMIT", target)

    preview = subscription_launch.preview_source_bundle()

    assert preview == {
        "schema_version": 1,
        "upstream_requests": 0,
        "target_commit": target,
        "source_head": later,
        "source_head_excluded": True,
        "advertised_heads": [[target, "refs/heads/thinharness-pin"]],
        "bundle_sha256": preview["bundle_sha256"],
        "bundle_persisted": False,
    }
    assert len(preview["bundle_sha256"]) == 64
    assert not list(tmp_path.rglob("*.bundle"))
