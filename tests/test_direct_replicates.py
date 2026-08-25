from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tbench import direct_replicates


def test_scope_is_exactly_two_new_thinharness_replicates() -> None:
    direct_replicates._validate_frozen_scope()
    config = json.loads(Path("configs/direct-openai-thinharness-replicates.json").read_text())

    assert [item["replicate_id"] for item in config["cells"]] == [
        "nginx-request-logging--thinharness--replicate-1",
        "sanitize-git-repo--thinharness--replicate-1",
    ]
    assert {item["harness"] for item in config["cells"]} == {"thinharness"}
    assert config["forbidden_cells"] == {
        "pi": True,
        "dna_insert": True,
        "policy_tasks": True,
        "all_other_tasks": True,
    }


def test_original_twenty_task_artifacts_are_immutable() -> None:
    direct_replicates._validate_original_immutable()


def test_original_concrete_errors_are_established_from_traces() -> None:
    for task in ("nginx-request-logging", "sanitize-git-repo"):
        comparison = direct_replicates._comparison(Path("artifacts/direct-openai-20task-pairwise"), task)
        # Pointing replicate at the frozen original must identify the same concrete error.
        assert comparison["original_error_established"] is True
        assert comparison["original_trace_marker_present"] is True
        assert comparison["replicate_error_established"] is True
        assert comparison["replicate_trace_marker_present"] is True
        assert comparison["concrete_error_recurred"] is True


def test_consumed_replicate_checkpoint_is_never_duplicated(tmp_path: Path) -> None:
    cell_id = "nginx-request-logging--thinharness"
    source = Path("artifacts/direct-openai-20task-pairwise/cells") / cell_id
    target = tmp_path / "cells" / cell_id
    shutil.copytree(source, target)
    checkpoint = json.loads((target / "CHECKPOINT.json").read_text())
    checkpoint["replicate_id"] = f"{cell_id}--replicate-1"
    (target / "CHECKPOINT.json").write_text(json.dumps(checkpoint))
    progress = {"mode": "real", "status": "running", "cells": [], "planned_cells": list(direct_replicates._cell_ids())}

    assert direct_replicates._recover_or_skip(tmp_path, progress, cell_id, "real") is True
    assert len(progress["cells"]) == 1
    assert progress["cells"][0]["never_rerun"] is True
    assert direct_replicates._recover_or_skip(tmp_path, progress, cell_id, "real") is True
    assert len(progress["cells"]) == 1


def test_replicate_launcher_uses_only_secure_doppler_key_injection(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    arguments = tmp_path / "doppler-arguments"
    doppler = tmp_path / "doppler"
    doppler.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >\"$ARGUMENTS\"\ntest -z \"${OPENAI_API_KEY:-}\"\n")
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
        [str(root / "scripts" / "run-direct-openai-thinharness-replicates.sh")],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    command = arguments.read_text()
    assert "--project api-keys" in command
    assert "--config dev_personal" in command
    assert "--only-secrets OPENAI_API_KEY" in command
    assert "--no-cache" in command
    assert "--no-fallback" in command
    assert "python -m tbench.direct_replicates run" in command
    assert "doppler configure debug" not in Path("scripts/run-direct-openai-thinharness-replicates.sh").read_text()
