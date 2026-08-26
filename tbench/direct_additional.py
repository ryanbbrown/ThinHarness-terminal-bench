"""Deterministic, no-launch preparation for ten additional matched task pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

from .constants import REPOSITORY_ROOT

BENCHMARK_ID = "direct-openai-additional-10-pairwise"
BASELINE_COMMIT = "70f5a7b69e7cbbcd09464e275b5a75a8821baa7f"
SUPERSEDED_COMMIT = "5feb120248de092d72771ff7f9630423350daebd"
CATALOG_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-catalog.json"
SELECTION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-selection.json"
EXCLUSION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-exclusion-proof.json"
RUNNER_SPEC_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-runner-spec.json"
POPULATION_REPORT_PATH = REPOSITORY_ROOT / "reports" / "direct-openai-additional-10-population.json"
PREPARATION_HASHES_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-additional-10-SHA256SUMS.json"
SNAPSHOT_DIR = REPOSITORY_ROOT / "evidence" / "terminal-bench-2-1-official-20260826"
SNAPSHOT_MANIFEST_PATH = SNAPSHOT_DIR / "manifest.json"
EMPIRICAL_EVIDENCE_PATH = SNAPSHOT_DIR / "derived" / "empirical-task-outcomes.json"

STRATUM_ORDER = ("easy", "medium", "hard", "unobserved")
ALLOCATION_PRIORITY = ("hard", "medium", "easy", "unobserved")
EASY_MINIMUM = Fraction(3, 4)
MEDIUM_MINIMUM = Fraction(1, 2)

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


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rate(successes: int, trials: int) -> dict[str, Any]:
    if trials == 0:
        return {"successes": successes, "accepted_trials": trials, "rate_fraction": None, "rate_decimal": None}
    fraction = Fraction(successes, trials)
    decimal = (Decimal(successes) / Decimal(trials)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return {
        "successes": successes,
        "accepted_trials": trials,
        "rate_fraction": str(fraction),
        "rate_decimal": str(decimal),
    }


def _task_from_judge_url(value: str) -> str:
    task = value.rstrip("/").rsplit("/", 1)[-1]
    if not task:
        raise RuntimeError(f"disqualified trial has no task in judge URL: {value}")
    return task


def _rewarded(trial: dict[str, Any]) -> bool:
    reward = (trial.get("rewards") or {}).get("reward")
    return isinstance(reward, (int, float)) and not isinstance(reward, bool) and reward > 0


def _catalog_rows() -> list[dict[str, Any]]:
    catalog = _load(CATALOG_PATH)
    population = catalog.get("population") or []
    names = [row.get("task") for row in population]
    if len(population) != 89 or len(set(names)) != 89 or names != sorted(names):
        raise RuntimeError("catalog is not the complete sorted 89-task population")
    if not set(PRIOR_TASKS) <= set(names):
        raise RuntimeError("an exclusion is absent from the frozen population")
    return population


def _validate_raw_snapshot(manifest: dict[str, Any]) -> None:
    for relative, identity in (manifest.get("raw_files") or {}).items():
        path = SNAPSHOT_DIR / relative
        if not path.is_file():
            raise RuntimeError(f"official snapshot raw file is missing: {relative}")
        if path.stat().st_size != identity.get("bytes") or _file_hash(path) != identity.get("sha256"):
            raise RuntimeError(f"official snapshot raw file differs: {relative}")
    if manifest.get("raw_source_set_sha256") != _canonical_hash(manifest.get("raw_files")):
        raise RuntimeError("official snapshot raw source-set hash differs")


def build_evidence_report() -> dict[str, Any]:
    """Derive all accepted official per-task outcomes from the bounded snapshot."""
    manifest = _load(SNAPSHOT_MANIFEST_PATH)
    _validate_raw_snapshot(manifest)
    catalog_by_task = {row["task"]: row for row in _catalog_rows()}
    leaderboard = _load(SNAPSHOT_DIR / "raw" / "hub-leaderboard-read.json")
    rows_by_pr = {row["metadata"]["pr_url"]["url"]: row for row in leaderboard["rows"]}
    aggregate: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    submissions: list[dict[str, Any]] = []

    for included in manifest.get("empirical_submissions") or []:
        submission = _load(SNAPSHOT_DIR / included["raw_submission_path"])
        pr_url = submission["metadata"]["pr_url"]["url"]
        hub_row = rows_by_pr.get(pr_url)
        if hub_row is None or hub_row.get("id") != included.get("hub_row_id"):
            raise RuntimeError(f"official Hub row does not match {included['submission_file']}")
        if submission.get("source_jobs") != included.get("source_jobs") or submission.get("source_filter") != included.get("source_filter"):
            raise RuntimeError(f"repository provenance differs for {included['submission_file']}")
        associations = json.loads((SNAPSHOT_DIR / included["raw_hub_trials_path"]).read_text(encoding="utf-8"))
        trials = [association.get("trial") for association in associations]
        if not trials or not all(isinstance(trial, dict) for trial in trials):
            raise RuntimeError(f"public Hub trial evidence is malformed for {included['submission_file']}")
        repository_count = len(submission.get("trials") or [])
        metric_count = submission["metrics"]["n_trials"]
        if len(trials) != repository_count or len(trials) != metric_count or len(trials) != hub_row.get("n_trials"):
            raise RuntimeError(f"trial coverage is incomplete for {included['submission_file']}")

        by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
        trial_ids: set[str] = set()
        for trial in trials:
            trial_id = trial.get("id")
            task_name = trial.get("task_name")
            if not isinstance(trial_id, str) or trial_id in trial_ids:
                raise RuntimeError(f"Hub trial IDs are missing or repeated for {included['submission_file']}")
            trial_ids.add(trial_id)
            if not isinstance(task_name, str) or not task_name.startswith("terminal-bench/"):
                raise RuntimeError(f"Hub task identity differs for {included['submission_file']}")
            task = task_name.split("/", 1)[1]
            catalog = catalog_by_task.get(task)
            if catalog is None or trial.get("task_content_hash") != catalog["task_package_digest"].removeprefix("sha256:"):
                raise RuntimeError(f"Hub task digest differs for {included['submission_file']}:{task}")
            by_task[task].append(trial)
        if set(by_task) != set(catalog_by_task) or min(map(len, by_task.values())) < 5:
            raise RuntimeError(f"submission does not cover all 89 tasks at least five times: {included['submission_file']}")

        disqualified = submission.get("disqualified_trials") or []
        disqualified_ids = [item.get("trial_id") for item in disqualified]
        if len(disqualified_ids) != len(set(disqualified_ids)) or not set(disqualified_ids) <= set(submission.get("trials") or []):
            raise RuntimeError(f"official disqualification records differ for {included['submission_file']}")
        disqualified_by_task = Counter(_task_from_judge_url(item["judge_trial"]) for item in disqualified)
        raw_successes = sum(_rewarded(trial) for trial in trials)
        post_disqualification_successes = raw_successes - len(disqualified)
        official_accuracy = round(100 * post_disqualification_successes / len(trials), 2)
        if official_accuracy != submission["metrics"]["accuracy"]:
            raise RuntimeError(f"official metric does not reconcile with Hub outcomes and disqualifications: {included['submission_file']}")

        per_task: dict[str, dict[str, Any]] = {}
        accepted_total = accepted_successes = 0
        for task in sorted(by_task):
            raw_task_successes = sum(_rewarded(trial) for trial in by_task[task])
            removed = disqualified_by_task[task]
            if removed > raw_task_successes or removed > len(by_task[task]):
                raise RuntimeError(f"disqualification cannot be removed from {included['submission_file']}:{task}")
            accepted_trials = len(by_task[task]) - removed
            successes = raw_task_successes - removed
            per_task[task] = {
                **_rate(successes, accepted_trials),
                "raw_trials": len(by_task[task]),
                "raw_successes": raw_task_successes,
                "disqualified_trials_excluded": removed,
            }
            aggregate[task][0] += successes
            aggregate[task][1] += accepted_trials
            accepted_total += accepted_trials
            accepted_successes += successes

        submissions.append(
            {
                "submission_file": included["submission_file"],
                "source_jobs": submission["source_jobs"],
                "source_filter": submission["source_filter"],
                "agent_display": submission["metadata"]["agent_display"],
                "model_display": submission["metadata"]["model_display"],
                "reasoning_effort": submission["metadata"]["reasoning_effort"],
                "hub_row_id": hub_row["id"],
                "hub_backing_job_ids": included["hub_backing_job_ids"],
                "raw_trials": len(trials),
                "raw_successes": raw_successes,
                "accepted_trials": accepted_total,
                "accepted_successes": accepted_successes,
                "disqualified_trials_excluded": len(disqualified),
                "task_coverage": len(by_task),
                "minimum_raw_trials_per_task": min(map(len, by_task.values())),
                "maximum_raw_trials_per_task": max(map(len, by_task.values())),
                "per_task": per_task,
            }
        )

    if len(submissions) != 16 or set(aggregate) != set(catalog_by_task):
        raise RuntimeError("empirical submission or task coverage differs from the frozen snapshot")

    pi_searches = _load(SNAPSHOT_DIR / "raw" / "hub-public-pi-job-searches.json")
    if any(record.get("response", {}).get("total") != 0 for record in pi_searches.get("records", [])):
        raise RuntimeError("the frozen public Pi search is no longer represented correctly")
    if any(item["source_filter"].get("agent", "").casefold() == "pi" for item in submissions):
        raise RuntimeError("Pi evidence is present but the frozen Pi-absence policy was used")

    closest = next(
        item
        for item in manifest["merged_without_current_hub_trials"]
        if item["source_filter"].get("model_name") == "gpt-5.6-sol" and item["source_filter"].get("agent") == "codex"
    )
    aggregate_rows = {
        task: _rate(values[0], values[1])
        for task, values in sorted(aggregate.items())
    }
    return {
        "schema_version": 1,
        "snapshot_id": manifest["snapshot_id"],
        "fetched_at_utc": manifest["fetched_at_utc"],
        "official_repository": manifest["official_sources"]["repository"],
        "official_urls": {
            "repository": manifest["official_sources"]["repository"]["url"],
            "leaderboard": manifest["official_sources"]["leaderboard"]["url"],
            "hub_dataset": manifest["official_sources"]["hub_dataset"]["url"],
        },
        "raw_source_set_sha256": manifest["raw_source_set_sha256"],
        "accepted_trial_policy": manifest["handling"]["accepted_trial"],
        "aggregation_policy": manifest["handling"]["fallback_rate"],
        "pi_evidence": {
            "verified_pi_per_task_evidence": False,
            "repository_merged_submission_matches": 0,
            "official_hub_leaderboard_row_matches": 0,
            "public_hub_job_search_totals": manifest["pi_evidence"]["hub_public_job_search_totals"],
            "rate_inference": "forbidden; no Pi rate is derived",
        },
        "pi_by_task": {},
        "closest_official_comparator": {
            "label": "exact-model OpenAI Codex comparator; not part of per-task empirical evidence",
            "submission_file": closest["submission_file"],
            "source_jobs": closest["source_jobs"],
            "source_filter": closest["source_filter"],
            "metrics": closest["metrics"],
            "per_task_evidence_available": False,
            "empirical_rate_use": "none",
            "limitation": closest["reason"],
        },
        "coverage": {
            "merged_submission_files_preserved": 20,
            "empirical_submissions": len(submissions),
            "merged_without_current_hub_row": len(manifest["merged_without_current_hub_trials"]),
            "excluded_incomplete_hub_trial_sets": len(manifest["excluded_incomplete_hub_trials"]),
            "tasks": len(aggregate_rows),
            "tasks_with_accepted_trials": sum(row["accepted_trials"] > 0 for row in aggregate_rows.values()),
            "tasks_without_accepted_trials": sum(row["accepted_trials"] == 0 for row in aggregate_rows.values()),
        },
        "excluded_merged_submissions": sorted(
            [*manifest["merged_without_current_hub_trials"], *manifest["excluded_incomplete_hub_trials"]],
            key=lambda item: item["submission_file"],
        ),
        "submissions": sorted(submissions, key=lambda item: item["submission_file"]),
        "aggregate_by_task": aggregate_rows,
    }


def choose_empirical_success(pi_rate: dict[str, Any] | None, broader_rate: dict[str, Any] | None) -> dict[str, Any]:
    """Prefer verified Pi evidence, then broader evidence, then unobserved."""
    if pi_rate is not None and pi_rate.get("accepted_trials", 0) > 0:
        return {**pi_rate, "source": "verified_official_pi"}
    if broader_rate is not None and broader_rate.get("accepted_trials", 0) > 0:
        return {**broader_rate, "source": "broader_verified_agent_aggregate"}
    return {**_rate(0, 0), "source": "unobserved"}


def _stratum(rate: dict[str, Any]) -> str:
    trials = rate["accepted_trials"]
    if trials == 0:
        return "unobserved"
    fraction = Fraction(rate["successes"], trials)
    if fraction >= EASY_MINIMUM:
        return "easy"
    if fraction >= MEDIUM_MINIMUM:
        return "medium"
    return "hard"


def _ordered_stratum(rows: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    if label == "unobserved":
        return sorted(rows, key=lambda row: row["task"])
    return sorted(
        rows,
        key=lambda row: (-Fraction(row["empirical_success"]["successes"], row["empirical_success"]["accepted_trials"]), row["task"]),
    )


def _allocate(strata: dict[str, list[dict[str, Any]]], total: int = 10) -> dict[str, int]:
    nonempty = [label for label in STRATUM_ORDER if strata[label]]
    if not nonempty:
        raise RuntimeError("no eligible empirical or unobserved stratum exists")
    base, remainder = divmod(total, len(nonempty))
    allocation = {label: min(base, len(strata[label])) if label in nonempty else 0 for label in STRATUM_ORDER}
    remaining = total - sum(allocation.values())
    priority = [label for label in ALLOCATION_PRIORITY if label in nonempty]
    while remaining:
        progressed = False
        for label in priority:
            if allocation[label] < len(strata[label]):
                allocation[label] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            raise RuntimeError("eligible strata cannot supply ten distinct tasks")
    if remainder and all(len(strata[label]) >= base + 1 for label in nonempty):
        expected_extra = priority[:remainder]
        actual_extra = [label for label in priority if allocation[label] == base + 1]
        if actual_extra != expected_extra:
            raise RuntimeError("balanced allocation priority differs")
    return allocation


def _spaced(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count == 0:
        return []
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [(index * (len(rows) - 1)) // (count - 1) for index in range(count)]
    if len(set(indices)) != count:
        raise RuntimeError("stratum is too small for its deterministic allocation")
    return [rows[index] for index in indices]


def build_reports() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the empirical selection and complete population report."""
    catalog = _catalog_rows()
    evidence = build_evidence_report()
    aggregate = evidence["aggregate_by_task"]
    complete: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    strata: dict[str, list[dict[str, Any]]] = {label: [] for label in STRATUM_ORDER}
    for catalog_row in catalog:
        task = catalog_row["task"]
        rate = choose_empirical_success(evidence["pi_by_task"].get(task), aggregate.get(task))
        row = {
            **catalog_row,
            "resource_metadata_role": "descriptive only; excluded from empirical strata and selection",
            "empirical_success": rate,
            "excluded_for_prior_evidence": task in PRIOR_TASKS,
        }
        if task in PRIOR_TASKS:
            row["prior_evidence"] = PRIOR_TASKS[task]
            row["selection_stratum"] = None
        else:
            label = _stratum(rate)
            row["selection_stratum"] = label
            strata[label].append(row)
            eligible.append(row)
        complete.append(row)

    for label in STRATUM_ORDER:
        strata[label] = _ordered_stratum(strata[label], label)
        for rank, row in enumerate(strata[label], 1):
            row["rank_within_stratum"] = rank
    allocation = _allocate(strata)
    chosen = [row for label in STRATUM_ORDER for row in _spaced(strata[label], allocation[label])]
    chosen_names = {row["task"] for row in chosen}
    for row in complete:
        row["selected"] = row["task"] in chosen_names
    cells = [f"{row['task']}--{harness}" for row in chosen for harness in ("pi", "thinharness")]

    old_selection = [
        "build-cython-ext",
        "largest-eigenval",
        "llm-inference-batching-scheduler",
        "mteb-retrieve",
        "schemelike-metacircular-eval",
        "torch-pipeline-parallelism",
        "torch-tensor-parallelism",
        "feal-linear-cryptanalysis",
        "fix-ocaml-gc",
        "caffe-cifar-10",
    ]
    selection = {
        "schema_version": 2,
        "frozen_before_spend": True,
        "benchmark_id": BENCHMARK_ID,
        "publication_baseline_commit": BASELINE_COMMIT,
        "supersedes_preparation_commit": SUPERSEDED_COMMIT,
        "superseded_selection_basis": "metadata-weighted expense proxy; forbidden for selection and stratification",
        "superseded_selected_tasks": old_selection,
        "dataset": "terminal-bench/terminal-bench-2-1@sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a",
        "official_evidence_snapshot": {
            "path": str(SNAPSHOT_DIR.relative_to(REPOSITORY_ROOT)),
            "manifest_sha256": _file_hash(SNAPSHOT_MANIFEST_PATH),
            "derived_evidence_sha256": _canonical_hash(evidence),
            "fetched_at_utc": evidence["fetched_at_utc"],
            "source_commit": evidence["official_repository"]["commit"],
            "raw_source_set_sha256": evidence["raw_source_set_sha256"],
        },
        "pi_evidence": evidence["pi_evidence"],
        "closest_official_comparator": evidence["closest_official_comparator"],
        "population_counts": {"complete": 89, "excluded": len(PRIOR_TASKS), "eligible": len(eligible)},
        "empirical_method": {
            "rate_source": (
                "verified Pi accepted official trials when available; otherwise pooled accepted trials from all 16 "
                "complete PR-linked official Hub submissions"
            ),
            "pi_status": "no verified official Pi per-task evidence; no Pi rate inferred",
            "accepted_trial": evidence["accepted_trial_policy"],
            "errors": "accepted errored or unrewarded trials remain failures in the denominator",
            "varying_trial_counts": (
                "pool integer successes and accepted trials; compare exact fractions without shrinkage or metadata weighting"
            ),
            "tie_break": "task name in ascending bytewise order after exact empirical rate",
            "missing_data": "zero accepted trials enters the explicit unobserved stratum; task name orders that stratum",
        },
        "stratum_definition": {
            "defined_before_selection": True,
            "easy": "accepted empirical success rate >= 3/4",
            "medium": "1/2 <= accepted empirical success rate < 3/4",
            "hard": "accepted empirical success rate < 1/2",
            "unobserved": "zero accepted official trials",
            "direction": "higher success is easier",
        },
        "strata": {
            label: {
                "count": len(rows),
                "easiest_boundary": (
                    {"task": rows[0]["task"], **rows[0]["empirical_success"]} if rows else None
                ),
                "hardest_boundary": (
                    {"task": rows[-1]["task"], **rows[-1]["empirical_success"]} if rows else None
                ),
                "chosen": [row["task"] for row in chosen if row["selection_stratum"] == label],
            }
            for label, rows in strata.items()
        },
        "allocation": {
            **allocation,
            "balance_rule": "divide ten equally across nonempty strata; assign remainders in hard, medium, easy, unobserved order",
            "capacity_rule": "if a stratum is too small, round-robin each remaining slot in the same priority order",
            "within_stratum_rule": (
                "sort observed tasks by exact rate descending then task name; choose floor(i * (N - 1) / (K - 1)) "
                "for i=0..K-1"
            ),
        },
        "selected": chosen,
        "planned_execution_order": cells,
        "planned_cells": 20,
        "attempts_per_cell": 1,
        "concurrency": 1,
        "retries": {"harbor": 0, "model": 0, "transport": 0, "provider": 0, "output": 0, "tool": 0},
        "selection_sha256": _canonical_hash(
            [
                (
                    row["task"],
                    row["empirical_success"]["successes"],
                    row["empirical_success"]["accepted_trials"],
                    row["selection_stratum"],
                )
                for row in chosen
            ]
        ),
    }
    population_report = {
        "schema_version": 2,
        "benchmark_id": BENCHMARK_ID,
        "supersedes_preparation_commit": SUPERSEDED_COMMIT,
        "catalog_sha256": _file_hash(CATALOG_PATH),
        "official_evidence_sha256": _canonical_hash(evidence),
        "coverage": evidence["coverage"],
        "pi_evidence": evidence["pi_evidence"],
        "exclusions": [{"task": task, **PRIOR_TASKS[task]} for task in sorted(PRIOR_TASKS)],
        "complete_population": complete,
        "eligible_population": eligible,
        "strata": {label: [row["task"] for row in rows] for label, rows in strata.items()},
        "selected_tasks": [row["task"] for row in chosen],
        "planned_execution_order": cells,
    }
    return selection, population_report


def _assert_equal(actual: dict[str, Any], expected: dict[str, Any], name: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{name} does not reproduce from the frozen official evidence and method")


def check() -> None:
    """Validate every preparation artifact without a launch-capable dependency."""
    evidence = build_evidence_report()
    _assert_equal(_load(EMPIRICAL_EVIDENCE_PATH), evidence, "official empirical evidence")
    snapshot_manifest = _load(SNAPSHOT_MANIFEST_PATH)
    for relative, identity in (snapshot_manifest.get("derived_files") or {}).items():
        path = SNAPSHOT_DIR / relative
        if not path.is_file() or path.stat().st_size != identity.get("bytes") or _file_hash(path) != identity.get("sha256"):
            raise RuntimeError(f"official snapshot derived file differs: {relative}")
    if snapshot_manifest.get("derived_source_set_sha256") != _canonical_hash(snapshot_manifest.get("derived_files")):
        raise RuntimeError("official snapshot derived source-set hash differs")
    expected_selection, expected_population = build_reports()
    _assert_equal(_load(SELECTION_PATH), expected_selection, "selection")
    _assert_equal(_load(POPULATION_REPORT_PATH), expected_population, "population report")
    exclusion = _load(EXCLUSION_PATH)
    if (
        exclusion.get("publication_baseline_commit") != BASELINE_COMMIT
        or exclusion.get("supersedes_preparation_commit") != SUPERSEDED_COMMIT
    ):
        raise RuntimeError("exclusion proof preparation identity differs")
    if exclusion.get("excluded_tasks") != sorted(PRIOR_TASKS):
        raise RuntimeError("exclusion proof differs from the complete prior-evidence union")
    selected_tasks = [row["task"] for row in expected_selection["selected"]]
    if exclusion.get("selected_tasks") != selected_tasks or exclusion.get("selected_conflicts") != []:
        raise RuntimeError("exclusion proof selection or freshness differs")
    runner = _load(RUNNER_SPEC_PATH)
    if runner.get("launch_enabled") is not False or runner.get("planned_execution_order") != expected_selection["planned_execution_order"]:
        raise RuntimeError("runner skeleton is launch-capable or its cell order differs")
    if runner.get("supersedes_preparation_commit") != SUPERSEDED_COMMIT:
        raise RuntimeError("runner does not supersede the metadata selection")
    budget = runner.get("budget") or {}
    if budget.get("per_cell_usd") != "3.00" or budget.get("total_usd") != "60.00":
        raise RuntimeError("budget differs from 20 cells at USD 3.00 each")
    if runner.get("methodology_identity_sha256") != _canonical_hash(runner.get("methodology_identity")):
        raise RuntimeError("runner methodology identity hash differs")
    expected_refs = [
        {
            key: row[key]
            for key in ("task", "task_package_digest", "task_toml_sha256", "instruction_sha256", "task_tree_manifest_sha256")
        }
        for row in expected_selection["selected"]
    ]
    if runner.get("selected_task_refs") != expected_refs:
        raise RuntimeError("runner task refs differ from the empirical selection")
    hashes = _load(PREPARATION_HASHES_PATH).get("files") or {}
    for name, expected_hash in hashes.items():
        path = REPOSITORY_ROOT / name
        if not path.is_file() or _file_hash(path) != expected_hash:
            raise RuntimeError(f"preparation identity file differs: {name}")


def render(output_dir: Path) -> None:
    """Render reproducible generated evidence and reports to a caller-selected directory."""
    evidence = build_evidence_report()
    selection, population = build_reports()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
        (EMPIRICAL_EVIDENCE_PATH.name, evidence),
        (SELECTION_PATH.name, selection),
        (POPULATION_REPORT_PATH.name, population),
    ):
        (output_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="No-launch official-evidence preparation validator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    if args.command == "check":
        check()
        print("additional ten-task preparation is deterministic, official-evidence based, and launch-disabled")
    else:
        render(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
