"""Frozen scope and new namespaces for the empirical ten-task campaign."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .constants import REPOSITORY_ROOT
from .direct_constants import DATASET_DIGEST as _DATASET_DIGEST
from .direct_constants import DATASET_NAME as _DATASET_NAME
from .direct_constants import HARBOR_VERSION as _HARBOR_VERSION
from .direct_constants import MODEL as _MODEL
from .direct_constants import THINHARNESS_COMMIT as _THINHARNESS_COMMIT

BENCHMARK_ID = "direct-openai-additional-10-pairwise"
DATASET_DIGEST = _DATASET_DIGEST
DATASET_NAME = _DATASET_NAME
HARBOR_VERSION = _HARBOR_VERSION
MODEL = _MODEL
THINHARNESS_COMMIT = _THINHARNESS_COMMIT
SELECTION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-selection.json"
RUNNER_SPEC_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-runner-spec.json"
EXCLUSION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-exclusion-proof.json"
PREPARATION_HASHES_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-SHA256SUMS.json"
SETTINGS_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-20task-settings.json"
ARTIFACT_DIR = REPOSITORY_ROOT / "artifacts" / BENCHMARK_ID
PREFLIGHT_DIR = REPOSITORY_ROOT / "artifacts" / f"{BENCHMARK_ID}-preflight"
JOBS_DIR = REPOSITORY_ROOT / "jobs" / BENCHMARK_ID
PREFLIGHT_JOBS_DIR = REPOSITORY_ROOT / "jobs" / f"{BENCHMARK_ID}-preflight"
RUNS_DIR = REPOSITORY_ROOT / "runs" / BENCHMARK_ID
REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}.json"
PREFLIGHT_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}-preflight.json"
PER_CELL_CAP_USD = Decimal("3.00")
TOTAL_CAP_USD = Decimal("60.00")
DOPPLER_LAUNCH_ID = "tb-additional-10-v1"


def selection() -> dict[str, Any]:
    value = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("additional ten-task selection is not an object")
    return value


TASKS = tuple(str(item["task"]) for item in selection()["selected"])
EXPECTED_CELLS = tuple(f"{task}--{harness}" for task in TASKS for harness in ("pi", "thinharness"))
