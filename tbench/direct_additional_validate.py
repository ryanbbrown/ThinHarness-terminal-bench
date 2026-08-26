"""Validation and reports for the empirical ten-task campaign."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import direct_validate
from .direct_additional_constants import (
    BENCHMARK_ID,
    EXPECTED_CELLS,
    PREFLIGHT_REPORT_PATH,
    REPORT_PATH,
    SELECTION_PATH,
)
from .durable import atomic_json


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON receipt is not an object: {path}")
    return value


def build_report(root: Path) -> dict[str, Any]:
    progress = _read(root / "progress.json")
    cells = progress.get("cells") or []
    usage_names = (
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    usage = {name: 0 for name in usage_names}
    cost = 0.0
    requests = 0
    rewards: list[float] = []
    statuses: dict[str, int] = {}
    for cell in cells:
        for name in usage:
            value = (cell.get("usage") or {}).get(name)
            if isinstance(value, int):
                usage[name] += value
        value = (cell.get("cost") or {}).get("api_equivalent_total")
        if isinstance(value, int | float):
            cost += float(value)
        requests += int(cell.get("request_count") or 0)
        reward = cell.get("reward")
        if isinstance(reward, int | float):
            rewards.append(float(reward))
        status = cell.get("status")
        if isinstance(status, str):
            statuses[status] = statuses.get(status, 0) + 1
    upstream_requests = sum(
        len(path.read_text(encoding="utf-8").splitlines()) for path in root.glob("cells/*/MODEL_REQUEST_STARTED.jsonl")
    )
    return {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "mode": progress.get("mode"),
        "status": progress.get("status"),
        "planned_cells": len(EXPECTED_CELLS),
        "checkpointed_cells": len(cells),
        "cells": cells,
        "aggregate": {
            "usage": usage,
            "api_equivalent_cost_usd": cost,
            "request_count": requests,
            "upstream_request_count": upstream_requests,
            "reward_sum": sum(rewards),
            "reward_count": len(rewards),
            "cell_status_counts": statuses,
        },
        "budget": progress.get("budget"),
        "runner_identity": progress.get("runner_identity"),
        "source_identity": progress.get("source_identity"),
        "stop": progress.get("stop"),
    }


def write_report(root: Path) -> dict[str, Any]:
    report = build_report(root)
    atomic_json(root / "SUMMARY.json", report)
    atomic_json(PREFLIGHT_REPORT_PATH if report["mode"] == "fake" else REPORT_PATH, report)
    return report


def write_hashes(root: Path) -> dict[str, str]:
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    atomic_json(root / "SHA256SUMS.json", hashes)
    return hashes


def validate_hashes(root: Path) -> None:
    expected = _read(root / "SHA256SUMS.json")
    actual = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    if actual != expected:
        raise RuntimeError("additional campaign artifact hash manifest differs")


def validate(root: Path, *, expected_mode: str) -> dict[str, Any]:
    progress = _read(root / "progress.json")
    if progress.get("benchmark_id") != BENCHMARK_ID or progress.get("mode") != expected_mode:
        raise RuntimeError("campaign progress identity differs")
    if progress.get("status") != "completed":
        raise RuntimeError("campaign is not complete")
    cells = progress.get("cells") or []
    if [item.get("cell_id") for item in cells] != list(EXPECTED_CELLS):
        raise RuntimeError("campaign checkpoint order differs from the frozen Pi-then-ThinHarness order")
    actual_dirs = sorted(path.name for path in (root / "cells").iterdir() if path.is_dir())
    if actual_dirs != sorted(EXPECTED_CELLS):
        raise RuntimeError("campaign artifact has a missing or unauthorized cell directory")
    upstream_requests = 0
    for cell_id in EXPECTED_CELLS:
        cell_dir = root / "cells" / cell_id
        checkpoint = direct_validate.validate_cell(
            cell_dir,
            mode=expected_mode,
            cell_id=cell_id,
            expected_cells=EXPECTED_CELLS,
            selection_path=SELECTION_PATH,
            benchmark_id=BENCHMARK_ID,
        )
        recorded = _read(cell_dir / "CHECKPOINT.json")
        if checkpoint != recorded:
            raise RuntimeError(f"checkpoint does not reproduce from receipts: {cell_id}")
        marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
        if marker.is_file():
            upstream_requests += len(marker.read_text(encoding="utf-8").splitlines())
    if expected_mode == "fake" and upstream_requests != 0:
        raise RuntimeError("no-model preflight made an upstream request")
    report = build_report(root)
    if _read(root / "SUMMARY.json") != report:
        raise RuntimeError("campaign summary does not reproduce")
    report_path = PREFLIGHT_REPORT_PATH if expected_mode == "fake" else REPORT_PATH
    if _read(report_path) != report:
        raise RuntimeError("campaign report namespace differs from its summary")
    validate_hashes(root)
    return report
