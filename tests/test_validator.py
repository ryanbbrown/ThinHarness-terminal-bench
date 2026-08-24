from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tbench.constants import MODEL_ID, PROMPT_SHA256, REPOSITORY_ROOT, THINHARNESS_COMMIT
from tbench.validate import ValidationError, validate_container_preflight


def receipt() -> dict:
    control_paths = {
        "budget.py": REPOSITORY_ROOT / "tbench" / "budget.py",
        "constants.py": REPOSITORY_ROOT / "tbench" / "constants.py",
        "container_runner.py": REPOSITORY_ROOT / "tbench" / "container_runner.py",
        "container-runtime-requirements.txt": REPOSITORY_ROOT / "configs" / "container-runtime-requirements.txt",
        "install-in-container.sh": REPOSITORY_ROOT / "scripts" / "install-in-container.sh",
        "system-prompt.md": REPOSITORY_ROOT / "prompts" / "pi-0.84.2-system-prompt.md",
    }
    schemas = [
        {"type": "function", "name": name, "description": name, "parameters": {"type": "object", "properties": {}}}
        for name in ("bash", "read", "edit", "write")
    ]
    return {
        "kind": "no-model-container-preflight",
        "model_calls": 0,
        "passed": True,
        "root": "/app",
        "execution": {"execution": "harbor-task-container", "cwd": "/app"},
        "staged_control_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in control_paths.items()},
        "thinharness": {"canonical_commit": THINHARNESS_COMMIT, "install": {"canonical_commit": THINHARNESS_COMMIT}},
        "prompt": {"sha256": PROMPT_SHA256},
        "tools": {
            "names": ["bash", "read", "edit", "write"],
            "origins": {
                "bash": {"plugin": "bash"},
                "read": {"plugin": "filesystem"},
                "edit": {"plugin": "filesystem"},
                "write": {"plugin": "filesystem"},
            },
            "schemas": schemas,
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
    path = REPOSITORY_ROOT / "artifacts" / "no-model-preflight" / "container-preflight.json"

    value = validate_container_preflight(path)

    assert value["model_calls"] == 0
    assert value["tools"]["names"] == ["bash", "read", "edit", "write"]


def test_validator_rejects_schema_receipt_without_parameters(tmp_path: Path) -> None:
    value = receipt()
    del value["tools"]["schemas"][0]["parameters"]
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value))

    with pytest.raises(ValidationError, match="complete Responses function schema"):
        validate_container_preflight(path)
