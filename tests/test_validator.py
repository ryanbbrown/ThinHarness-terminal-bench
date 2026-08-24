from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tbench.constants import MODEL_ID, PROMPT_SHA256, REPOSITORY_ROOT, THINHARNESS_COMMIT
from tbench.schema_contract import schema_sha256
from tbench.validate import (
    ValidationError,
    validate_container_preflight,
    validate_ledger_recorded_costs,
    validate_paid_artifacts,
    validate_preflight_artifacts,
)


def receipt() -> dict:
    control_paths = {
        "budget.py": REPOSITORY_ROOT / "tbench" / "budget.py",
        "constants.py": REPOSITORY_ROOT / "tbench" / "constants.py",
        "container_runner.py": REPOSITORY_ROOT / "tbench" / "container_runner.py",
        "container_security.py": REPOSITORY_ROOT / "tbench" / "container_security.py",
        "schema_contract.py": REPOSITORY_ROOT / "tbench" / "schema_contract.py",
        "container-runtime-requirements.txt": REPOSITORY_ROOT / "configs" / "container-runtime-requirements.txt",
        "native-tool-schemas.json": REPOSITORY_ROOT / "configs" / "native-tool-schemas.json",
        "install-in-container.sh": REPOSITORY_ROOT / "scripts" / "install-in-container.sh",
        "system-prompt.md": REPOSITORY_ROOT / "prompts" / "pi-0.84.2-system-prompt.md",
    }
    schemas = json.loads((REPOSITORY_ROOT / "configs" / "native-tool-schemas.json").read_text())["schemas"]
    overflow = b"0123456789abcdef" * 8192
    overflow_hash = hashlib.sha256(overflow).hexdigest()
    return {
        "kind": "no-model-container-preflight",
        "model_calls": 0,
        "passed": True,
        "root": "/app",
        "execution": {"execution": "harbor-task-container", "cwd": "/app"},
        "staged_control_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in control_paths.items()},
        "thinharness": {
            "canonical_commit": THINHARNESS_COMMIT,
            "install": {"canonical_commit": THINHARNESS_COMMIT, "source_mode": "canonical-github"},
        },
        "prompt": {"sha256": PROMPT_SHA256},
        "tools": {
            "names": ["bash", "read", "edit", "write"],
            "origins": {
                "bash": {"plugin": "bash"},
                "read": {"plugin": "filesystem"},
                "edit": {"plugin": "filesystem"},
                "write": {"plugin": "filesystem"},
            },
            "schema_sha256": {schema["name"]: schema_sha256(schema) for schema in schemas},
            "schemas": schemas,
        },
        "credential_isolation": {
            "ordinary_inheritance_removed": True,
            "process_security": {"platform": "linux", "dumpable": 0, "cap_sys_ptrace": False},
            "native_bash": {
                "own_environment_openai_key_absent": True,
                "own_environment_sentinel_absent": True,
                "parent_environ_read_blocked": True,
                "result": {"ok": True},
            },
        },
        "native_bash_overflow": {
            "native_tool": "bash",
            "plugin_origin": "bash",
            "tool_source": "bash",
            "max_output_bytes": 40_000,
            "model_facing_result_bytes": 40_500,
            "model_facing_result_bounded": True,
            "model_facing_result_contains_truncation_marker": True,
            "full_output_bytes": len(overflow),
            "full_output_sha256": overflow_hash,
            "stdout_bytes": len(overflow),
            "stdout_omitted_bytes": len(overflow) - 40_000,
            "stdout_retained_ranges": [[0, 20_000], [len(overflow) - 20_000, len(overflow)]],
            "retained_bytes": 40_000,
            "stdout_drain_complete": True,
            "artifact_path": ".thinharness/outputs/bash-test-stdout",
            "artifact_path_relative": True,
            "artifact_path_contained_by_root": True,
            "artifact_resolved_path": "/app/.thinharness/outputs/bash-test-stdout",
            "artifact_full_bytes_verified": True,
            "retrieval": {
                "native_tool": "bash",
                "ok": True,
                "expected_line": f"{len(overflow)} {overflow_hash}",
                "content": f"stdout:\n{len(overflow)} {overflow_hash}\n",
            },
        },
        "wire": {
            "base_url": "https://api.openai.com/v1",
            "model": MODEL_ID,
            "reasoning": {"effort": "xhigh", "summary": "auto"},
            "text": {"verbosity": "low"},
            "provider_retries": 0,
            "agent_output_retries": 0,
            "agent_tool_retries": 0,
            "payload_probe": {
                "model": MODEL_ID,
                "reasoning": {"effort": "xhigh", "summary": "auto"},
                "text": {"verbosity": "low"},
                "network_requests": 0,
            },
        },
        "verifier_handoff": {"harbor_owns_verifier": True},
    }


def test_validator_accepts_complete_independent_preflight_contract(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt()))

    assert validate_container_preflight(path)["passed"] is True


def test_committed_harbor_preflight_proves_native_container_architecture() -> None:
    path = REPOSITORY_ROOT / "artifacts" / "no-model-preflight-84105f07" / "container-preflight.json"
    if not path.exists():
        pytest.skip("generated by the required Harbor container preflight")

    value = validate_container_preflight(path)
    durable = validate_preflight_artifacts(path.parent)

    assert value["model_calls"] == 0
    assert value["tools"]["names"] == ["bash", "read", "edit", "write"]
    assert durable["overflow"]["full_output_bytes"] == 131_072
    assert durable["overflow"]["retrieval_verified"] is True


def test_committed_paid_artifacts_prove_complete_verifier_passing_e2e() -> None:
    artifact_dir = REPOSITORY_ROOT / "artifacts" / "paid-e2e"

    value = validate_paid_artifacts(artifact_dir)

    assert value["passed"] is True
    assert value["reward"] == 1.0
    assert value["requests"] == 4
    assert value["tokens"] == {
        "input_tokens": 14771,
        "ordinary_input_tokens": 12,
        "cached_input_tokens": 9976,
        "cache_write_tokens": 4783,
        "output_tokens": 3060,
        "reasoning_tokens": 2384,
    }
    assert value["tool_count"] == 3
    assert value["tool_counts"] == {"bash": 2, "write": 1}
    assert value["actual_cash_cost_usd"] is None
    assert value["original_ledger_recorded_api_equivalent_cost_usd"] == pytest.approx(0.096848)
    assert value["api_equivalent_cost_usd"] == pytest.approx(0.12674175)
    assert all(path.startswith("artifacts/paid-e2e/") for path in value["receipts"].values())
    report = json.loads((REPOSITORY_ROOT / "reports" / "implementation-e2e.json").read_text())
    assert report == value


def test_current_paid_artifacts_reproduce_commit_keyed_e2e_report() -> None:
    artifact_dir = REPOSITORY_ROOT / "artifacts" / "paid-e2e-84105f07"

    value = validate_paid_artifacts(artifact_dir)

    assert value["passed"] is True
    assert value["reward"] == 1.0
    assert value["requests"] == 4
    assert value["tokens"] == {
        "input_tokens": 13_474,
        "ordinary_input_tokens": 12,
        "cached_input_tokens": 9_135,
        "cache_write_tokens": 4_327,
        "output_tokens": 2_604,
        "reasoning_tokens": 1_956,
    }
    assert value["tool_count"] == 3
    assert value["tool_counts"] == {"bash": 2, "write": 1}
    assert value["actual_cash_cost_usd"] is None
    assert value["api_equivalent_cost_usd"] == pytest.approx(0.10979125)
    assert value["prior_implementation_spend_usd"] == pytest.approx(0.12674175)
    assert value["cumulative_implementation_spend_usd"] == pytest.approx(0.236533)
    assert value["identity"]["thinharness_commit"] == THINHARNESS_COMMIT
    assert value["identity"]["source_bundle_sha256"] == (
        "5b1b53ee96796ee50a13fb22f01a0f922927ca322fd2db1cf173b8cf8c05d0a2"
    )
    assert value["identity"]["wheel_sha256"] == (
        "1954f0edbea2b4fc340f93d1eacade72cd5cd9b9fa709b76683e978a57ae1a16"
    )
    assert value["model_settings"]["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert all(path.startswith("artifacts/paid-e2e-84105f07/") for path in value["receipts"].values())
    report = json.loads((REPOSITORY_ROOT / "reports" / "implementation-e2e-84105f07.json").read_text())
    assert report == value


def test_validator_rejects_internally_consistent_but_mispriced_ledger() -> None:
    ledger = copy.deepcopy(json.loads((REPOSITORY_ROOT / "artifacts" / "paid-e2e" / "api-budget.json").read_text()))
    ledger["requests"][0]["api_equivalent_cost_usd"] += 0.001
    ledger["spent_usd"] += 0.001

    with pytest.raises(ValidationError, match="differs from raw token pricing"):
        validate_ledger_recorded_costs(ledger)


def test_paid_artifact_validator_recalculates_corrected_costs(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "artifacts" / "paid-e2e"
    copied = tmp_path / "paid-e2e"
    shutil.copytree(source, copied)
    reconciliation_path = copied / "corrected-accounting-reconciliation.json"
    reconciliation = json.loads(reconciliation_path.read_text())
    reconciliation["requests"][0]["corrected_api_equivalent_cost_usd"] += 0.001
    reconciliation_path.write_text(json.dumps(reconciliation, indent=2, sort_keys=True) + "\n")
    manifest_path = copied / "SHA256SUMS.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["corrected-accounting-reconciliation.json"] = hashlib.sha256(reconciliation_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    with pytest.raises(ValidationError, match="differs from raw token pricing"):
        validate_paid_artifacts(copied)


def test_validator_rejects_schema_receipt_without_parameters(tmp_path: Path) -> None:
    value = receipt()
    del value["tools"]["schemas"][0]["parameters"]
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value))

    with pytest.raises(ValidationError, match="frozen complete contract"):
        validate_container_preflight(path)


def test_validator_rejects_unverified_native_bash_overflow(tmp_path: Path) -> None:
    value = receipt()
    value["native_bash_overflow"]["artifact_full_bytes_verified"] = False
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value))

    with pytest.raises(ValidationError, match="full artifact verification"):
        validate_container_preflight(path)
