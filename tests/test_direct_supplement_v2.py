from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tbench import direct_supplement_v2
from tbench.direct_budget import BudgetBlocked, DirectBudgetLedger


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _ledger(path: Path) -> DirectBudgetLedger:
    return direct_supplement_v2.SupplementV2BudgetLedger(
        path,
        benchmark_id=direct_supplement_v2.BENCHMARK_ID,
        per_cell_cap=Decimal("10.00"),
        total_cap=Decimal("10.00"),
    )


def test_scope_is_exactly_one_ordered_native_thinharness_doom_attempt() -> None:
    direct_supplement_v2._validate_scope()
    selection = _read(direct_supplement_v2.SELECTION_PATH)

    assert selection["planned_execution_order"] == ["make-doom-for-mips--thinharness--supplemental-v2-attempt-1"]
    assert selection["cells"] == selection["selected"]
    assert [(cell["task"], cell["harness"], cell["attempt"]) for cell in selection["cells"]] == [("make-doom-for-mips", "thinharness", 1)]
    encoded = json.dumps(selection).lower()
    assert "model-extraction-relu-logits" not in encoded
    assert '"harness": "pi"' not in encoded
    assert "--pi" not in encoded


def test_doom_task_package_and_instruction_are_bound_to_the_frozen_source_spec() -> None:
    cell = direct_supplement_v2._cell()
    spec = _read(direct_supplement_v2.RUNNER_SPEC_PATH)
    source = next(item for item in spec["selected_task_refs"] if item["task"] == "make-doom-for-mips")
    names = ("task_package_digest", "instruction_sha256", "task_toml_sha256", "task_tree_manifest_sha256")

    assert {name: cell[name] for name in names} == {name: source[name] for name in names}
    assert cell["task_package_digest"] == "sha256:2d83dd3dee8e0f055e09973934cf0d7e3169a9cd90704cba5c8940b170be9498"


def test_model_harness_timeout_harbor_and_all_retry_identities_are_exact() -> None:
    settings = _read(direct_supplement_v2.SETTINGS_PATH)
    execution = settings["execution"]
    model = execution["model"]

    assert (execution["thinharness_version"], execution["thinharness_commit"]) == (
        "0.7.0",
        "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef",
    )
    assert model["model"] == "gpt-5.6-sol"
    assert model["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert model["text"] == {"verbosity": "low"}
    assert model["request_timeout_seconds"] == execution["provider_timeout_seconds"] == 1800
    assert model["retries"] == {"model": 0, "output": 0, "provider": 0, "tool": 0, "transport": 0}
    assert execution["agent_retries"] == 0
    assert execution["harbor"] == {
        "agent_setup_timeout_multiplier": 3.0,
        "attempts_per_cell": 1,
        "concurrency": 1,
        "environment": "docker",
        "retries": 0,
        "timeout_multiplier": 1.0,
        "version": "0.21.0",
    }


def test_production_launch_seam_can_only_submit_the_authorized_cell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    root = tmp_path / "preflight"
    runs = tmp_path / "runs"

    @contextmanager
    def source_bundle():
        yield SimpleNamespace(
            sha256="0" * 64,
            target_commit="84105f07bb9c1ad366fc8fe4fef49e700f5e88ef",
            target_tree="1" * 40,
            target_commit_sha256="2" * 64,
            advertised_ref="refs/thinharness-terminal-bench/exact-commit",
            source_head="84105f07bb9c1ad366fc8fe4fef49e700f5e88ef",
            source_head_excluded=False,
        )

    def run_cell(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        cell_dir = root / "cells" / direct_supplement_v2.CELL_ID
        cell_dir.mkdir(parents=True)
        return {
            "cell_id": direct_supplement_v2.CELL_ID,
            "mode": "fake",
            "status": "completed",
            "real_model_attempted": False,
            "never_rerun": False,
            "usage": {},
            "cost": {"api_equivalent_total": 0},
            "reward": 0,
        }

    monkeypatch.setattr(direct_supplement_v2, "PREFLIGHT_DIR", root)
    monkeypatch.setattr(direct_supplement_v2, "PREFLIGHT_JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(direct_supplement_v2, "PREFLIGHT_REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(direct_supplement_v2, "RUNS_DIR", runs)
    monkeypatch.setattr(direct_supplement_v2, "_LOCK_PATH", runs / "launch.lock")
    monkeypatch.setattr(direct_supplement_v2, "_validate_environment", lambda mode: None)
    monkeypatch.setattr(direct_supplement_v2, "_validate_scope", lambda: None)
    monkeypatch.setattr(direct_supplement_v2, "_validate_prior_evidence", lambda: None)
    monkeypatch.setattr(direct_supplement_v2, "_repository_identity", lambda: {"files_sha256": "identity"})
    monkeypatch.setattr(direct_supplement_v2, "_source_bundle", source_bundle)
    monkeypatch.setattr(direct_supplement_v2.direct_launch, "_run_cell", run_cell)
    monkeypatch.setattr(direct_supplement_v2, "validate", lambda *args, **kwargs: {})

    assert direct_supplement_v2.run("preflight") == 0
    assert len(calls) == 1
    assert calls[0]["task"] == "make-doom-for-mips"
    assert calls[0]["harness"] == "thinharness"
    assert calls[0]["expected_cells"] == ("make-doom-for-mips--thinharness",)
    assert calls[0]["benchmark_id"] == direct_supplement_v2.BENCHMARK_ID


def test_request_start_marker_permanently_consumes_the_only_v2_cell(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget-ledger.json")
    ledger.reserve_cell(direct_supplement_v2.CELL_ID)
    ledger.authorize_request(direct_supplement_v2.CELL_ID)
    ledger.request_started(direct_supplement_v2.CELL_ID)

    restarted = _ledger(tmp_path / "budget-ledger.json")
    assert restarted.state["cells"][direct_supplement_v2.CELL_ID]["consumed"] is True
    with pytest.raises(BudgetBlocked, match="already has durable budget state"):
        restarted.reserve_cell(direct_supplement_v2.CELL_ID)


def test_restart_skips_a_recorded_consumed_cell_without_calling_harbor(tmp_path: Path) -> None:
    cell_dir = tmp_path / "cells" / direct_supplement_v2.CELL_ID
    cell_dir.mkdir(parents=True)
    checkpoint = direct_supplement_v2._decorate(
        {
            "cell_id": direct_supplement_v2.CELL_ID,
            "mode": "real",
            "status": "consumed_interrupted",
            "real_model_attempted": True,
            "never_rerun": True,
        }
    )
    from tbench.durable import atomic_json

    atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
    direct_supplement_v2._write_receipt(tmp_path, checkpoint)
    progress = {"cells": [checkpoint]}

    assert direct_supplement_v2._recover(tmp_path, progress, "real", None) == "skip"
    assert progress["cells"] == [checkpoint]


def test_usd_ten_cap_checkpoints_one_in_flight_overshoot_and_blocks_all_more_requests(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget-ledger.json")
    ledger.reserve_cell(direct_supplement_v2.CELL_ID)
    ledger.request_started(direct_supplement_v2.CELL_ID)

    cost = ledger.settle_usage(
        direct_supplement_v2.CELL_ID,
        {
            "ordinary_input_tokens": 0,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 333_334,
        },
    )

    assert cost == Decimal("10.000020")
    assert ledger.blocked is not None
    assert ledger.blocked["reason"] == "per-cell USD 10.00 cap reached or crossed"
    with pytest.raises(BudgetBlocked, match="10.00"):
        ledger.authorize_request(direct_supplement_v2.CELL_ID)


def test_published_original_and_v1_evidence_remains_byte_for_byte_immutable() -> None:
    direct_supplement_v2._validate_prior_evidence()
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            "40a004c90e0e2ae6e13d40568389389dd7fa0f03",
            "--",
            "artifacts/direct-openai-additional-10-pairwise",
            "artifacts/direct-openai-additional-10-thinharness-supplement-v1",
            "configs/direct-openai-additional-10-thinharness-supplement-v1-selection.json",
            "configs/direct-openai-additional-10-thinharness-supplement-v1-settings.json",
            "reports/direct-openai-additional-10-pairwise.json",
            "reports/direct-openai-additional-10-thinharness-supplement-v1.json",
            "reports/direct-openai-additional-10-thinharness-supplement-v1-direct-comparison.json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_secure_launcher_uses_only_doppler_openai_secret_and_v2_entrypoint(tmp_path: Path) -> None:
    arguments = tmp_path / "doppler-arguments"
    doppler = tmp_path / "doppler"
    doppler.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >"$ARGUMENTS"\ntest -z "${OPENAI_API_KEY:-}"\n', encoding="utf-8")
    doppler.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment.update(
        {"PATH": f"{tmp_path}:{environment['PATH']}", "ARGUMENTS": str(arguments), "TB_THINHARNESS_LOCAL_SOURCE": str(tmp_path)}
    )

    completed = subprocess.run(
        ["scripts/run-direct-openai-additional-10-thinharness-supplement-v2.sh"],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    command = arguments.read_text(encoding="utf-8")
    assert "--project api-keys" in command
    assert "--config dev_personal" in command
    assert "--only-secrets OPENAI_API_KEY" in command
    assert "--no-cache" in command
    assert "--no-fallback" in command
    assert "tbench.direct_supplement_v2 run" in command
    assert _read(direct_supplement_v2.SETTINGS_PATH)["credential_boundary"]["key_persisted"] is False
