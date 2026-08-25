"""Deterministic, no-launch preparation for ten additional matched task pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from .constants import REPOSITORY_ROOT

BENCHMARK_ID = "direct-openai-additional-10-pairwise"
BASELINE_COMMIT = "70f5a7b69e7cbbcd09464e275b5a75a8821baa7f"
CATALOG_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-catalog.json"
SELECTION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-selection.json"
EXCLUSION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-exclusion-proof.json"
RUNNER_SPEC_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-runner-spec.json"
POPULATION_REPORT_PATH = REPOSITORY_ROOT / "reports" / "direct-openai-additional-10-population.json"
PREPARATION_HASHES_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-SHA256SUMS.json"

PRIOR_TASKS: dict[str, dict[str, str]] = {
    "build-pmars": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "extract-elf": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "fix-code-vulnerability": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "hf-model-inference": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "kv-store-grpc": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "overfull-hbox": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "regex-log": {"evidence": "prior real and consumed", "source": "evidence/migration-manifest.json"},
    "reshard-c4-data": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "write-compressor": {"evidence": "prior attempted/paid selection", "source": "configs/subscription-smoke-selection.json"},
    "fix-git": {"evidence": "prior real subscription cell", "source": "configs/subscription-smoke-selection.json"},
    "prove-plus-comm": {"evidence": "prior real subscription cell", "source": "configs/subscription-smoke-selection.json"},
    "raman-fitting": {"evidence": "prior real subscription cells", "source": "configs/subscription-smoke-selection.json"},
    "crack-7z-hash": {"evidence": "prior real matched pair", "source": "configs/subscription-recovery-selection.json"},
    "configure-git-webserver": {"evidence": "prior real matched pair", "source": "configs/subscription-extension-selection.json"},
    "constraints-scheduling": {"evidence": "prior real matched pair", "source": "configs/subscription-extension-selection.json"},
    "pytorch-model-recovery": {"evidence": "prior real matched pair", "source": "configs/subscription-extension-selection.json"},
}

WEIGHTS = {
    "expert_time": Decimal("0.30"),
    "agent_timeout": Decimal("0.15"),
    "verifier_timeout": Decimal("0.15"),
    "cpu": Decimal("0.10"),
    "memory": Decimal("0.10"),
    "storage": Decimal("0.05"),
    "image_build": Decimal("0.15"),
}
IMAGE_BUILD_WEIGHTS = {
    "build_timeout": Decimal("0.20"),
    "environment_context": Decimal("0.40"),
    "dockerfile_instructions": Decimal("0.20"),
    "dockerfile_copy_add": Decimal("0.20"),
}
DIRECT_SELECTED = tuple(
    item["task"]
    for item in json.loads((REPOSITORY_ROOT / "configs" / "direct-openai-20task-selection.json").read_text(encoding="utf-8"))["selected"]
)
for _task in DIRECT_SELECTED:
    PRIOR_TASKS[_task] = {
        "evidence": "prior real direct matched pair; replicate evidence also applies where present",
        "source": "configs/direct-openai-20task-selection.json",
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _ranges(rows: list[dict[str, Any]]) -> dict[str, tuple[Decimal, Decimal]]:
    fields = {
        "expert_time": "expert_time_estimate_min",
        "agent_timeout": "agent_timeout_sec",
        "verifier_timeout": "verifier_timeout_sec",
        "cpu": "cpus",
        "memory": "memory_mb",
        "storage": "storage_mb",
        "build_timeout": "build_timeout_sec",
        "environment_context": "environment_context_bytes",
        "dockerfile_instructions": "dockerfile_instruction_count",
        "dockerfile_copy_add": "dockerfile_copy_add_count",
    }
    result = {}
    for name, field in fields.items():
        values = [Decimal(str(row[field])) for row in rows if row[field] is not None]
        result[name] = (min(values), max(values))
    return result


def _normalized(value: Any, bounds: tuple[Decimal, Decimal], *, missing_high: bool = False) -> Decimal:
    low, high = bounds
    if value is None:
        if missing_high:
            return Decimal(1)
        raise RuntimeError("proxy input is missing")
    if high == low:
        return Decimal(0)
    return (Decimal(str(value)) - low) / (high - low)


def score_population() -> tuple[list[dict[str, Any]], dict[str, tuple[Decimal, Decimal]]]:
    """Return all eligible tasks in deterministic proxy order and the frozen ranges."""
    catalog = _load(CATALOG_PATH)
    population = catalog.get("population") or []
    names = [row.get("task") for row in population]
    if len(population) != 89 or len(set(names)) != 89 or names != sorted(names):
        raise RuntimeError("catalog is not the complete sorted 89-task population")
    if not set(PRIOR_TASKS) <= set(names):
        raise RuntimeError("an exclusion is absent from the frozen population")
    eligible = [row for row in population if row["task"] not in PRIOR_TASKS]
    bounds = _ranges(eligible)
    scored = []
    for row in eligible:
        image_build = sum(
            (
                IMAGE_BUILD_WEIGHTS[name] * _normalized(row[field], bounds[name])
                for name, field in {
                    "build_timeout": "build_timeout_sec",
                    "environment_context": "environment_context_bytes",
                    "dockerfile_instructions": "dockerfile_instruction_count",
                    "dockerfile_copy_add": "dockerfile_copy_add_count",
                }.items()
            ),
            start=Decimal(0),
        )
        components = {
            "expert_time": _normalized(row["expert_time_estimate_min"], bounds["expert_time"], missing_high=True),
            "agent_timeout": _normalized(row["agent_timeout_sec"], bounds["agent_timeout"]),
            "verifier_timeout": _normalized(row["verifier_timeout_sec"], bounds["verifier_timeout"]),
            "cpu": _normalized(row["cpus"], bounds["cpu"]),
            "memory": _normalized(row["memory_mb"], bounds["memory"]),
            "storage": _normalized(row["storage_mb"], bounds["storage"]),
            "image_build": image_build,
        }
        score = sum((WEIGHTS[name] * value for name, value in components.items()), start=Decimal(0)) * 100
        item = dict(row)
        item["proxy_components_normalized"] = {
            name: str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)) for name, value in components.items()
        }
        item["expense_proxy_score"] = str(score.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
        scored.append(item)
    scored.sort(key=lambda item: (Decimal(item["expense_proxy_score"]), item["task"]))
    return scored, bounds


def _strata(scored: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    base, remainder = divmod(len(scored), 3)
    sizes = [base + (1 if index < remainder else 0) for index in range(3)]
    labels = ("low", "medium", "high")
    result = {}
    offset = 0
    for label, size in zip(labels, sizes, strict=True):
        rows = scored[offset : offset + size]
        for row in rows:
            row["stratum"] = label
            row["eligible_rank"] = offset + rows.index(row) + 1
        result[label] = rows
        offset += size
    return result


def _spaced(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [(index * (len(rows) - 1)) // (count - 1) for index in range(count)]
    if len(set(indices)) != count:
        raise RuntimeError("stratum is too small for the frozen allocation")
    return [rows[index] for index in indices]


def build_reports() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the frozen selection and complete scored-population report."""
    scored, bounds = score_population()
    strata = _strata(scored)
    chosen = _spaced(strata["low"], 3) + _spaced(strata["medium"], 3) + _spaced(strata["high"], 4)
    cells = [f"{row['task']}--{harness}" for row in chosen for harness in ("pi", "thinharness")]
    normalization = {
        name: {"minimum": str(low), "maximum": str(high), "method": "eligible-population min-max; constants normalize to zero"}
        for name, (low, high) in bounds.items()
    }
    selection = {
        "schema_version": 1,
        "frozen_before_spend": True,
        "benchmark_id": BENCHMARK_ID,
        "publication_baseline_commit": BASELINE_COMMIT,
        "dataset": "terminal-bench/terminal-bench-2-1@sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a",
        "population_counts": {"complete": 89, "excluded": len(PRIOR_TASKS), "eligible": len(scored)},
        "expense_proxy": {
            "method": "weighted min-max score over the complete eligible population",
            "weights": {name: str(value) for name, value in WEIGHTS.items()},
            "image_build_subweights": {name: str(value) for name, value in IMAGE_BUILD_WEIGHTS.items()},
            "normalization": normalization,
            "missing_expert_time": "normalize to 1.0 (highest burden)",
            "tie_break": "task name in ascending bytewise order",
        },
        "strata": {
            label: {
                "count": len(rows),
                "first_rank": rows[0]["eligible_rank"],
                "last_rank": rows[-1]["eligible_rank"],
                "lower_boundary": {"score": rows[0]["expense_proxy_score"], "task": rows[0]["task"]},
                "upper_boundary": {"score": rows[-1]["expense_proxy_score"], "task": rows[-1]["task"]},
                "chosen": [row["task"] for row in chosen if row["stratum"] == label],
            }
            for label, rows in strata.items()
        },
        "allocation": {
            "low": 3,
            "medium": 3,
            "high": 4,
            "extra_task_rule": "assign the remainder to high to increase coverage of infrastructure and expense risk",
            "within_stratum_rule": "choose floor(i * (N - 1) / (K - 1)) for i from 0 through K - 1 in proxy order",
        },
        "selected": chosen,
        "planned_execution_order": cells,
        "planned_cells": 20,
        "attempts_per_cell": 1,
        "concurrency": 1,
        "retries": {"harbor": 0, "model": 0, "transport": 0, "provider": 0, "output": 0, "tool": 0},
        "selection_sha256": _canonical_hash([(row["task"], row["expense_proxy_score"], row["stratum"]) for row in chosen]),
    }
    population_report = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "catalog_sha256": hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest(),
        "exclusions": [{"task": task, **PRIOR_TASKS[task]} for task in sorted(PRIOR_TASKS)],
        "eligible_population": scored,
        "strata": {label: [row["task"] for row in rows] for label, rows in strata.items()},
        "selected_tasks": [row["task"] for row in chosen],
        "planned_execution_order": cells,
    }
    return selection, population_report


def _assert_equal(actual: dict[str, Any], expected: dict[str, Any], name: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{name} does not reproduce from the frozen catalog and method")


def check() -> None:
    """Validate every preparation artifact without any launch-capable dependency."""
    expected_selection, expected_population = build_reports()
    _assert_equal(_load(SELECTION_PATH), expected_selection, "selection")
    _assert_equal(_load(POPULATION_REPORT_PATH), expected_population, "population report")
    exclusion = _load(EXCLUSION_PATH)
    if exclusion.get("publication_baseline_commit") != BASELINE_COMMIT:
        raise RuntimeError("exclusion proof baseline differs")
    if exclusion.get("excluded_tasks") != sorted(PRIOR_TASKS):
        raise RuntimeError("exclusion proof differs from the complete prior-evidence union")
    if exclusion.get("selected_conflicts") != []:
        raise RuntimeError("selected task conflicts with prior evidence")
    runner = _load(RUNNER_SPEC_PATH)
    if runner.get("launch_enabled") is not False or runner.get("planned_execution_order") != expected_selection["planned_execution_order"]:
        raise RuntimeError("runner skeleton is launch-capable or its cell order differs")
    budget = runner.get("budget") or {}
    if budget.get("per_cell_usd") != "3.00" or budget.get("total_usd") != "60.00":
        raise RuntimeError("budget differs from 20 cells at USD 3.00 each")
    if runner.get("methodology_identity_sha256") != _canonical_hash(runner.get("methodology_identity")):
        raise RuntimeError("runner methodology identity hash differs")
    hashes = _load(PREPARATION_HASHES_PATH).get("files") or {}
    for name, expected_hash in hashes.items():
        path = REPOSITORY_ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f"preparation identity file differs: {name}")


def render(output_dir: Path) -> None:
    """Render reproducible generated reports to a caller-selected directory."""
    selection, population = build_reports()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in ((SELECTION_PATH.name, selection), (POPULATION_REPORT_PATH.name, population)):
        (output_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="No-launch preparation validator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        check()
        print("additional ten-task preparation is deterministic and launch-disabled")
    else:
        render(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
