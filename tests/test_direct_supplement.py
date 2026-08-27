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

from tbench import direct_launch, direct_supplement, direct_validate
from tbench.direct_budget import BudgetBlocked, DirectBudgetLedger
from tbench.durable import atomic_json


def _ledger(path: Path) -> DirectBudgetLedger:
    return DirectBudgetLedger(
        path,
        benchmark_id=direct_supplement.BENCHMARK_ID,
        per_cell_cap=Decimal("10.00"),
        total_cap=Decimal("20.00"),
    )


def _output_usage(tokens: int) -> dict[str, int]:
    return {
        "ordinary_input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": tokens,
    }


def test_scope_is_the_exact_two_ordered_supplemental_thinharness_attempts() -> None:
    direct_supplement._validate_scope()
    selection = json.loads(direct_supplement.SELECTION_PATH.read_text(encoding="utf-8"))

    assert selection["planned_execution_order"] == [
        "model-extraction-relu-logits--thinharness--supplemental-attempt-1",
        "make-doom-for-mips--thinharness--supplemental-attempt-1",
    ]
    assert [item["cell_id"] for item in selection["cells"]] == list(direct_supplement.EXPECTED_CELL_IDS)
    assert {item["harness"] for item in selection["cells"]} == {"thinharness"}
    assert {item["attempt"] for item in selection["cells"]} == {1}
    assert all("--pi" not in item["supplemental_cell_id"] for item in selection["cells"])


def test_preflight_validation_maps_supplemental_ids_to_base_task_harness_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = direct_validate._selection_map(direct_supplement.SELECTION_PATH)
    cell = direct_supplement._cells()[0]
    observed: dict[str, Any] = {}

    def validate_cell(cell_dir: Path, **kwargs: Any) -> dict[str, Any]:
        observed.update({"cell_dir": cell_dir, **kwargs})
        return {
            "cell_id": cell["cell_id"],
            "mode": "fake",
            "status": "completed",
            "real_model_attempted": False,
            "never_rerun": False,
        }

    monkeypatch.setattr(direct_supplement.direct_validate, "validate_cell", validate_cell)
    checkpoint = direct_supplement._reproduce_checkpoint(tmp_path, cell, "fake")

    assert selected[cell["task"]]["task_package_digest"] == cell["task_package_digest"]
    assert observed["cell_dir"] == tmp_path / "cells" / cell["cell_id"]
    assert observed["cell_id"] == cell["cell_id"]
    assert observed["expected_cells"] == direct_supplement.EXPECTED_CELL_IDS
    assert checkpoint["supplemental_cell_id"] == cell["supplemental_cell_id"]


def test_task_packages_and_instruction_hashes_are_bound_to_the_published_spec() -> None:
    selection = json.loads(direct_supplement.SELECTION_PATH.read_text(encoding="utf-8"))
    spec = json.loads(direct_supplement.RUNNER_SPEC_PATH.read_text(encoding="utf-8"))
    refs = {item["task"]: item for item in spec["selected_task_refs"]}
    names = ("task_package_digest", "instruction_sha256", "task_toml_sha256", "task_tree_manifest_sha256")

    for cell in selection["cells"]:
        assert {name: cell[name] for name in names} == {name: refs[cell["task"]][name] for name in names}


def test_published_model_harness_and_retry_identities_are_exact() -> None:
    settings = json.loads(direct_supplement.SETTINGS_PATH.read_text(encoding="utf-8"))
    execution = settings["execution"]
    model = execution["model"]

    assert execution["harnesses"] == ["thinharness"]
    assert (execution["thinharness_version"], execution["thinharness_commit"]) == (
        "0.7.0",
        "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef",
    )
    assert model["model"] == "gpt-5.6-sol"
    assert model["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert model["text"] == {"verbosity": "low"}
    assert model["request_timeout_seconds"] == 1800
    assert execution["provider_timeout_seconds"] == 1800
    assert set(model["retries"].values()) == {0}
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
    command = direct_launch._harbor_command(
        cell_id=direct_supplement.EXPECTED_CELL_IDS[0],
        task="model-extraction-relu-logits",
        harness="thinharness",
        mode="fake",
        job_name="test",
        jobs_dir=Path("jobs/test"),
    )
    assert command[command.index("--n-attempts") + 1] == "1"
    assert command[command.index("--n-concurrent") + 1] == "1"
    assert command[command.index("--max-retries") + 1] == "0"


def test_failed_no_model_preflight_is_preserved_with_hashes_and_zero_upstream_requests() -> None:
    root = Path("artifacts/direct-openai-additional-10-thinharness-supplement-v1-preflight-failure-20260827-192054-keyerror-selected")
    failure = _read_json(root / "FAILURE.json")
    expected = _read_json(root / "SHA256SUMS.json")
    actual = {
        str(path.relative_to(root)): direct_supplement._sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }

    assert failure["status"] == "preserved_no_model_preflight_failure"
    assert failure["error"] == {"type": "KeyError", "message": "'selected'"}
    assert failure["upstream_request_count"] == 0
    assert failure["paid_model_calls"] is False
    assert actual == expected


def test_original_frozen_campaign_evidence_is_immutable() -> None:
    direct_supplement._validate_original_evidence()
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            "0d04252c9b1961cf801544afb5329ab36785200b",
            "--",
            "artifacts/direct-openai-additional-10-pairwise",
            "jobs/direct-openai-additional-10-pairwise",
            "runs/direct-openai-additional-10-pairwise",
            "reports/direct-openai-additional-10-pairwise.json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_request_start_permanently_consumes_the_supplemental_cell(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget-ledger.json")
    cell_id = direct_supplement.EXPECTED_CELL_IDS[0]
    ledger.reserve_cell(cell_id)
    ledger.authorize_request(cell_id)
    ledger.request_started(cell_id)

    restarted = _ledger(tmp_path / "budget-ledger.json")
    assert restarted.state["cells"][cell_id]["consumed"] is True
    with pytest.raises(BudgetBlocked, match="already has durable budget state"):
        restarted.reserve_cell(cell_id)


def test_restart_recovers_and_skips_a_consumed_complete_cell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cell = direct_supplement._cells()[0]
    cell_dir = tmp_path / "cells" / cell["cell_id"]
    cell_dir.mkdir(parents=True)
    (cell_dir / "MODEL_REQUEST_STARTED.jsonl").write_text('{"sequence":1}\n', encoding="utf-8")
    checkpoint = direct_supplement._decorate(
        {
            "cell_id": cell["cell_id"],
            "mode": "real",
            "status": "completed",
            "real_model_attempted": True,
            "never_rerun": True,
        },
        cell,
    )
    progress: dict[str, Any] = {
        "mode": "real",
        "status": "running",
        "cells": [],
        "planned_cells": list(direct_supplement.EXPECTED_SUPPLEMENTAL_IDS),
    }
    ledger = _ledger(tmp_path / "budget-ledger.json")
    ledger.reserve_cell(cell["cell_id"])
    ledger.request_started(cell["cell_id"])
    ledger.settle_usage(cell["cell_id"], _output_usage(1))
    monkeypatch.setattr(direct_supplement, "_reproduce_checkpoint", lambda root, selected, mode: checkpoint)

    assert direct_supplement._recover(tmp_path, progress, cell, "real", ledger) == "skip"
    assert progress["cells"] == [checkpoint]
    assert ledger.state["cells"][cell["cell_id"]]["status"] == "settled"
    assert (cell_dir / "SUPPLEMENTAL_RECEIPT.json").is_file()


def test_restart_skips_a_recorded_consumed_cell_without_reproduction(tmp_path: Path) -> None:
    cell = direct_supplement._cells()[0]
    cell_dir = tmp_path / "cells" / cell["cell_id"]
    cell_dir.mkdir(parents=True)
    checkpoint = direct_supplement._decorate(
        {
            "cell_id": cell["cell_id"],
            "mode": "real",
            "status": "consumed_interrupted",
            "real_model_attempted": True,
            "never_rerun": True,
        },
        cell,
    )
    atomic_json(cell_dir / "CHECKPOINT.json", checkpoint)
    direct_supplement._write_receipt(tmp_path, cell, checkpoint)
    progress = {
        "mode": "real",
        "status": "running",
        "cells": [checkpoint],
        "planned_cells": list(direct_supplement.EXPECTED_SUPPLEMENTAL_IDS),
    }

    assert direct_supplement._recover(tmp_path, progress, cell, "real", None) == "skip"
    assert progress["cells"] == [checkpoint]


def test_exact_repeated_first_policy_refusal_stops_before_second_cell(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    root = tmp_path / "preflight"
    jobs = tmp_path / "jobs"
    runs = tmp_path / "runs"
    progress = {
        "schema_version": 1,
        "benchmark_id": direct_supplement.BENCHMARK_ID,
        "label": "authorized supplemental reruns; not original campaign cells",
        "original_benchmark_id": direct_supplement.ORIGINAL_BENCHMARK_ID,
        "mode": "fake",
        "status": "running",
        "planned_cells": list(direct_supplement.EXPECTED_SUPPLEMENTAL_IDS),
        "cells": [],
        "runner_identity": {"files_sha256": "identity"},
        "source_identity": {},
        "budget": None,
    }

    @contextmanager
    def source_bundle():
        yield SimpleNamespace(sha256="0" * 64)

    def run_cell(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs["task"])
        (root / "cells" / f"{kwargs['task']}--thinharness").mkdir(parents=True)
        return {
            "cell_id": f"{kwargs['task']}--thinharness",
            "mode": "fake",
            "status": "model_attempt_failed",
            "real_model_attempted": True,
            "never_rerun": True,
            "model_attempt_failure": {
                "response": direct_supplement.POLICY_RESPONSE,
                "response_sha256": direct_supplement._canonical_sha256(direct_supplement.POLICY_RESPONSE),
                "credit_exhausted": False,
            },
        }

    monkeypatch.setattr(direct_supplement, "PREFLIGHT_DIR", root)
    monkeypatch.setattr(direct_supplement, "PREFLIGHT_JOBS_DIR", jobs)
    monkeypatch.setattr(direct_supplement, "PREFLIGHT_REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(direct_supplement, "RUNS_DIR", runs)
    monkeypatch.setattr(direct_supplement, "_LOCK_PATH", runs / "launch.lock")
    monkeypatch.setattr(direct_supplement, "_validate_environment", lambda mode: None)
    monkeypatch.setattr(direct_supplement, "_validate_scope", lambda: None)
    monkeypatch.setattr(direct_supplement, "_validate_original_evidence", lambda: None)
    monkeypatch.setattr(direct_supplement, "_repository_identity", lambda: {"files_sha256": "identity"})
    monkeypatch.setattr(direct_supplement, "_source_bundle", source_bundle)
    monkeypatch.setattr(direct_supplement, "_load_progress", lambda *args: progress)
    monkeypatch.setattr(direct_supplement.direct_launch, "_run_cell", run_cell)

    assert direct_supplement.run("preflight") == 2
    assert calls == ["model-extraction-relu-logits"]
    assert _read_json(root / "OUTCOME.json")["status"] == "policy_refusal"
    refusal = _read_json(root / "cells" / direct_supplement.EXPECTED_CELL_IDS[0] / "POLICY_REFUSAL.json")
    assert refusal["never_retry"] is True
    assert refusal["repeats_original"] is True


def test_usd_ten_cell_cap_checkpoints_one_in_flight_overshoot_and_blocks_later_work(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path / "budget-ledger.json")
    first, second = direct_supplement.EXPECTED_CELL_IDS
    ledger.reserve_cell(first)
    ledger.request_started(first)

    cost = ledger.settle_usage(first, _output_usage(333_334))

    assert cost == Decimal("10.000020")
    assert Decimal(ledger.state["cells"][first]["spent_usd"]) == Decimal("10.000020")
    assert ledger.blocked is not None
    with pytest.raises(BudgetBlocked):
        ledger.reserve_cell(second)


def test_api_equivalent_and_provider_reported_costs_are_separate(tmp_path: Path) -> None:
    progress = {
        "benchmark_id": direct_supplement.BENCHMARK_ID,
        "mode": "real",
        "status": "completed",
        "cells": [
            {
                "status": "completed",
                "usage": {},
                "cost": {"api_equivalent_total": 1.25},
                "reward": 0,
            }
        ],
        "runner_identity": {},
        "source_identity": {},
        "budget": {},
    }
    atomic_json(tmp_path / "progress.json", progress)
    audit = tmp_path / "cells" / "cell" / "gateway-audit.jsonl"
    audit.parent.mkdir(parents=True)
    audit.write_text(
        json.dumps({"status": 200, "cost_usd": {"actual_cash": 0.75}}) + "\n",
        encoding="utf-8",
    )

    aggregate = direct_supplement.build_report(tmp_path)["aggregate"]
    assert aggregate["api_equivalent_cost_usd"] == "1.25"
    assert aggregate["provider_reported_cost_usd"] == "0.75"
    assert aggregate["provider_reported_cost_complete"] is True


def test_secure_launcher_injects_only_the_doppler_openai_key_without_persisting_it(tmp_path: Path) -> None:
    arguments = tmp_path / "doppler-arguments"
    doppler = tmp_path / "doppler"
    doppler.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >"$ARGUMENTS"\ntest -z "${OPENAI_API_KEY:-}"\n', encoding="utf-8")
    doppler.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment.update(
        {
            "PATH": f"{tmp_path}:{environment['PATH']}",
            "ARGUMENTS": str(arguments),
            "TB_THINHARNESS_LOCAL_SOURCE": str(tmp_path),
        }
    )

    completed = subprocess.run(
        ["scripts/run-direct-openai-additional-10-thinharness-supplement-v1.sh"],
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
    assert "tbench.direct_supplement run" in command
    settings = json.loads(direct_supplement.SETTINGS_PATH.read_text(encoding="utf-8"))
    assert settings["credential_boundary"]["key_persisted"] is False


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
