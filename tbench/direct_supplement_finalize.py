"""Validate the stopped paid supplement and build its direct-comparison report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import direct_supplement, direct_validate
from .constants import REPOSITORY_ROOT
from .durable import atomic_json

PAID_ROOT = REPOSITORY_ROOT / "artifacts" / direct_supplement.BENCHMARK_ID
ORIGINAL_REPORT_PATH = REPOSITORY_ROOT / "reports" / "direct-openai-additional-10-pairwise.json"
COMPARISON_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{direct_supplement.BENCHMARK_ID}-direct-comparison.json"
FIRST_CELL_ID = direct_supplement.EXPECTED_CELL_IDS[0]
FIRST_SUPPLEMENTAL_ID = direct_supplement.EXPECTED_SUPPLEMENTAL_IDS[0]
DOOM_CELL_ID = direct_supplement.EXPECTED_CELL_IDS[1]
DOOM_SUPPLEMENTAL_ID = direct_supplement.EXPECTED_SUPPLEMENTAL_IDS[1]
EXPECTED_USAGE = {
    "input_tokens": 6625,
    "ordinary_input_tokens": 9,
    "cached_input_tokens": 3510,
    "cache_write_tokens": 3106,
    "output_tokens": 3447,
    "reasoning_tokens": 3168,
}
EXPECTED_API_COST = Decimal("0.12462250")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON evidence is not an object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not values or not all(isinstance(item, dict) for item in values):
        raise RuntimeError(f"JSONL evidence is empty or malformed: {path}")
    return values


def _seconds(started: str, finished: str) -> Decimal:
    return Decimal(
        str(
            (
                datetime.fromisoformat(finished.replace("Z", "+00:00")) - datetime.fromisoformat(started.replace("Z", "+00:00"))
            ).total_seconds()
        )
    )


def _request_cost(audit: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, Decimal], Decimal]:
    usage = {name: 0 for name in EXPECTED_USAGE}
    components = {name: Decimal(0) for name in ("ordinary_input", "cached_input", "cache_write", "output")}
    for item in audit:
        if item.get("status") != 200:
            continue
        item_usage = item.get("usage")
        cost = item.get("cost_usd")
        if not isinstance(item_usage, dict) or not isinstance(cost, dict):
            raise RuntimeError("successful supplemental request lacks usage or cost")
        for name in usage:
            value = item_usage.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeError(f"successful supplemental request has invalid usage: {name}")
            usage[name] += value
        expected = {
            "ordinary_input": Decimal(item_usage["ordinary_input_tokens"]) * Decimal("5.0") / Decimal(1_000_000),
            "cached_input": Decimal(item_usage["cached_input_tokens"]) * Decimal("0.5") / Decimal(1_000_000),
            "cache_write": Decimal(item_usage["cache_write_tokens"]) * Decimal("6.25") / Decimal(1_000_000),
            "output": Decimal(item_usage["output_tokens"]) * Decimal("30.0") / Decimal(1_000_000),
        }
        recorded_components = cost.get("components")
        if not isinstance(recorded_components, dict):
            raise RuntimeError("successful supplemental request lacks cost components")
        for name, value in expected.items():
            recorded = recorded_components.get(name)
            if not isinstance(recorded, int | float) or Decimal(str(recorded)) != value:
                raise RuntimeError(f"supplemental request cost component differs: {name}")
            components[name] += value
        recorded_total = cost.get("api_equivalent_total")
        expected_total = sum(expected.values(), Decimal(0))
        if not isinstance(recorded_total, int | float) or abs(Decimal(str(recorded_total)) - expected_total) > Decimal("1e-15"):
            raise RuntimeError("supplemental request API-equivalent total differs")
        if cost.get("actual_cash") is not None:
            raise RuntimeError("provider-reported cash cost was expected to be absent")
    return usage, components, sum(components.values(), Decimal(0))


def validate_paid_evidence(root: Path = PAID_ROOT) -> dict[str, Any]:
    direct_supplement._validate_scope()
    direct_supplement._validate_original_evidence()
    direct_supplement._validate_hashes(root)
    progress = _read(root / "progress.json")
    outcome = _read(root / "OUTCOME.json")
    summary = _read(root / "SUMMARY.json")
    report = _read(REPOSITORY_ROOT / "reports" / f"{direct_supplement.BENCHMARK_ID}.json")
    stop = {
        "cell_id": FIRST_SUPPLEMENTAL_ID,
        "reason": "exact original cyber_policy refusal repeated; never retry",
    }
    if (
        progress.get("benchmark_id") != direct_supplement.BENCHMARK_ID
        or progress.get("mode") != "real"
        or progress.get("status") != "policy_refusal"
        or progress.get("planned_cells") != list(direct_supplement.EXPECTED_SUPPLEMENTAL_IDS)
        or progress.get("stop") != stop
        or outcome.get("status") != "policy_refusal"
        or outcome.get("checkpointed_cells") != 1
        or outcome.get("stop") != stop
        or summary != report
    ):
        raise RuntimeError("paid supplemental stop state differs")
    cells = progress.get("cells")
    if not isinstance(cells, list) or len(cells) != 1 or cells[0].get("supplemental_cell_id") != FIRST_SUPPLEMENTAL_ID:
        raise RuntimeError("paid supplemental consumed-cell denominator differs")
    actual_dirs = sorted(path.name for path in (root / "cells").iterdir() if path.is_dir())
    if actual_dirs != [FIRST_CELL_ID]:
        raise RuntimeError("paid supplemental cell directories differ")
    cell = direct_supplement._cells()[0]
    cell_dir = root / "cells" / FIRST_CELL_ID
    checkpoint = _read(cell_dir / "CHECKPOINT.json")
    reproduced = direct_supplement._decorate(
        direct_validate.cell_summary(cell_dir, status="model_attempt_failed", real_model_attempted=True), cell
    )
    if checkpoint != reproduced or cells[0] != checkpoint:
        raise RuntimeError("paid supplemental checkpoint does not reproduce")
    direct_supplement._validate_receipt(root, cell, checkpoint)
    refusal = _read(cell_dir / "POLICY_REFUSAL.json")
    if (
        not direct_supplement._policy_refusal(checkpoint)
        or refusal.get("never_retry") is not True
        or refusal.get("repeats_original") is not True
        or refusal.get("response") != direct_supplement.POLICY_RESPONSE
        or refusal.get("response_sha256") != refusal.get("original_response_sha256")
    ):
        raise RuntimeError("paid supplemental policy refusal differs")
    markers = _jsonl(cell_dir / "MODEL_REQUEST_STARTED.jsonl")
    audit = _jsonl(cell_dir / "gateway-audit.jsonl")
    if len(markers) != 4 or len(audit) != 4:
        raise RuntimeError("paid supplemental request denominator differs")
    for sequence, (marker, item) in enumerate(zip(markers, audit, strict=True), 1):
        if (
            marker.get("benchmark_id") != direct_supplement.BENCHMARK_ID
            or marker.get("cell_id") != FIRST_CELL_ID
            or marker.get("sequence") != sequence
            or marker.get("transport_retries") != 0
            or item.get("benchmark_id") != direct_supplement.BENCHMARK_ID
            or item.get("cell_id") != FIRST_CELL_ID
            or item.get("sequence") != sequence
        ):
            raise RuntimeError("paid supplemental request identity differs")
    if any(item.get("status") != 200 or item.get("response_model") != "gpt-5.6-sol" for item in audit[:3]):
        raise RuntimeError("paid supplemental successful response identity differs")
    terminal = audit[-1]
    if (
        terminal.get("status") != 400
        or terminal.get("response") != direct_supplement.POLICY_RESPONSE
        or terminal.get("credit_exhausted") is not False
        or terminal.get("usage") is not None
        or terminal.get("cost_usd") is not None
    ):
        raise RuntimeError("paid supplemental terminal refusal differs")
    usage, components, cost = _request_cost(audit)
    if usage != EXPECTED_USAGE or cost != EXPECTED_API_COST:
        raise RuntimeError("paid supplemental usage or API-equivalent cost differs")
    checkpoint_cost = checkpoint.get("cost") or {}
    if checkpoint.get("usage") != usage or abs(Decimal(str(checkpoint_cost.get("api_equivalent_total"))) - cost) > Decimal("1e-15"):
        raise RuntimeError("paid supplemental checkpoint accounting differs")
    trial = direct_supplement._trial(cell_dir)
    if trial is None:
        raise RuntimeError("paid supplemental Harbor trial is absent")
    harbor = _read(trial / "result.json")
    native = _read(trial / "agent" / "thinharness-direct-result.json")
    if (
        harbor.get("verifier_result") is not None
        or harbor.get("verifier") is not None
        or checkpoint.get("reward") is not None
        or checkpoint.get("verifier_outcome") is not None
        or native.get("request_count") != 3
        or native.get("response_models") != ["gpt-5.6-sol"]
        or not isinstance(harbor.get("exception_info"), dict)
        or "cyber_policy" not in str((harbor.get("exception_info") or {}).get("exception_message"))
        or any((trial / "verifier" / name).exists() for name in ("ctrf.json", "reward.txt", "test-stdout.txt"))
    ):
        raise RuntimeError("paid supplemental absent verifier outcome or native receipt differs")
    ledger = _read(root / "budget-ledger.json")
    entry = (ledger.get("cells") or {}).get(FIRST_CELL_ID)
    if (
        not isinstance(entry, dict)
        or entry.get("consumed") is not True
        or entry.get("request_count") != 4
        or Decimal(str(entry.get("spent_usd"))) != cost
        or ledger.get("active_cell") != FIRST_CELL_ID
        or set(ledger.get("cells") or {}) != {FIRST_CELL_ID}
        or Decimal(str(ledger.get("total_spent_usd"))) != cost
    ):
        raise RuntimeError("paid supplemental ledger differs")
    if (root / "cells" / DOOM_CELL_ID).exists() or list(root.rglob(f"*{DOOM_CELL_ID}*")):
        raise RuntimeError("Doom supplemental artifact must remain absent")
    jobs = REPOSITORY_ROOT / "jobs" / direct_supplement.BENCHMARK_ID
    if jobs.exists() and any(DOOM_CELL_ID in path.name for path in jobs.rglob("*")):
        raise RuntimeError("Doom supplemental job must remain absent")
    timing = checkpoint.get("timing") or {}
    return {
        "progress": progress,
        "checkpoint": checkpoint,
        "audit": audit,
        "usage": usage,
        "components": components,
        "cost": cost,
        "timing": timing,
        "harbor": harbor,
    }


def build_comparison_report(root: Path = PAID_ROOT) -> dict[str, Any]:
    paid = validate_paid_evidence(root)
    original = _read(ORIGINAL_REPORT_PATH)
    pairs = original.get("paired_results")
    if not isinstance(pairs, list) or len(pairs) != 8:
        raise RuntimeError("original paired-result denominator differs")
    pi_reward = sum((Decimal(str(pair["pi"]["verifier_reward"])) for pair in pairs), Decimal(0))
    thin_reward = sum((Decimal(str(pair["thinharness"]["verifier_reward"])) for pair in pairs), Decimal(0))
    if pi_reward != Decimal(7) or thin_reward != Decimal(7):
        raise RuntimeError("original paired-result score differs")
    original_cells = {item["cell_id"]: item for item in original.get("cells") or []}
    timing = paid["timing"]
    request_seconds = [Decimal(str(value)) for value in timing.get("request_seconds") or []]
    launcher_wall = Decimal(str(timing["launcher_finished_at"])) - Decimal(str(timing["launcher_started_at"]))
    harbor = paid["harbor"]
    return {
        "schema_version": 1,
        "report_id": f"{direct_supplement.BENCHMARK_ID}-direct-comparison",
        "label": "supplemental direct-comparison update; original frozen campaign unchanged",
        "original_benchmark_id": direct_supplement.ORIGINAL_BENCHMARK_ID,
        "supplemental_benchmark_id": direct_supplement.BENCHMARK_ID,
        "status": "incomplete_after_repeated_policy_refusal",
        "stop": {
            "explanation": (
                "The exact model-extraction cyber_policy refusal repeated. Its supplemental attempt is permanently consumed. "
                "The stop rule prevented the Doom supplemental attempt from launching, so Doom remains unconsumed and must not run."
            ),
            "refusal_response_sha256": direct_supplement._canonical_sha256(direct_supplement.POLICY_RESPONSE),
            "model_extraction_never_retry": True,
            "doom_never_launch": True,
        },
        "denominators": {
            "planned_task_pairs": 10,
            "original_verifier_complete_pairs": 8,
            "post_supplement_verifier_complete_pairs": 8,
            "incomplete_pairs": 2,
            "supplemental_authorized_cells": 2,
            "supplemental_consumed_cells": 1,
            "supplemental_verifier_outcomes": 0,
            "supplemental_unconsumed_cells": 1,
            "pair_policy": original.get("paired_result_policy"),
        },
        "observed_eight_pair_subset": {
            "scope": "Descriptive only; this is not the unavailable full ten-pair score.",
            "denominator": 8,
            "pi_reward_sum": str(pi_reward),
            "thinharness_reward_sum": str(thin_reward),
            "pi_minus_thinharness_reward_sum": str(pi_reward - thin_reward),
        },
        "full_ten_pair_score": {
            "available": False,
            "reason": (
                "Model extraction still has no ThinHarness verifier outcome after the repeated refusal, and Doom has no "
                "ThinHarness run because the supplemental stop rule left it unrun."
            ),
            "missing_tasks": ["model-extraction-relu-logits", "make-doom-for-mips"],
        },
        "affected_tasks": {
            "model-extraction-relu-logits": {
                "original_pi_status": original_cells["model-extraction-relu-logits--pi"]["status"],
                "original_pi_reward": original_cells["model-extraction-relu-logits--pi"]["verifier_reward"],
                "original_thinharness_status": original_cells[FIRST_CELL_ID]["status"],
                "supplemental_thinharness_status": "model_attempt_failed",
                "supplemental_verifier_outcome_available": False,
                "pair_included": False,
            },
            "make-doom-for-mips": {
                "original_pi_status": original_cells["make-doom-for-mips--pi"]["status"],
                "original_pi_reward": original_cells["make-doom-for-mips--pi"]["verifier_reward"],
                "original_thinharness_status": original_cells[DOOM_CELL_ID]["status"],
                "supplemental_thinharness_status": "unrun_after_repeated_policy_refusal",
                "supplemental_consumed": False,
                "pair_included": False,
            },
        },
        "supplemental_paid_observation": {
            "cell_id": FIRST_SUPPLEMENTAL_ID,
            "requests": 4,
            "successful_requests": 3,
            "terminal_requests": 1,
            "tool_calls": 4,
            "usage": paid["usage"],
            "cost": {
                "currency": "USD",
                "api_equivalent_usd": str(paid["cost"].quantize(Decimal("0.00000001"))),
                "provider_reported_actual_cash_usd": None,
                "components": {name: str(value.quantize(Decimal("0.00000001"))) for name, value in paid["components"].items()},
            },
            "timing": {
                "launcher_wall_seconds": str(launcher_wall),
                "harbor_wall_seconds": str(_seconds(harbor["started_at"], harbor["finished_at"])),
                "environment_setup_seconds": str(
                    _seconds(harbor["environment_setup"]["started_at"], harbor["environment_setup"]["finished_at"])
                ),
                "agent_setup_seconds": str(_seconds(harbor["agent_setup"]["started_at"], harbor["agent_setup"]["finished_at"])),
                "agent_execution_seconds": str(_seconds(harbor["agent_execution"]["started_at"], harbor["agent_execution"]["finished_at"])),
                "native_agent_seconds": str(Decimal(str(timing["native_agent_seconds"]))),
                "request_seconds": [str(value) for value in request_seconds],
                "request_total_seconds": str(sum(request_seconds, Decimal(0))),
                "verifier_seconds": None,
            },
            "verifier_outcome": None,
        },
        "evidence": {
            "original_report": str(ORIGINAL_REPORT_PATH.relative_to(REPOSITORY_ROOT)),
            "original_report_sha256": direct_supplement._sha256(ORIGINAL_REPORT_PATH),
            "supplemental_artifact": str(root.relative_to(REPOSITORY_ROOT)),
            "supplemental_sha256_manifest": str((root / "SHA256SUMS.json").relative_to(REPOSITORY_ROOT)),
            "supplemental_sha256_manifest_sha256": direct_supplement._sha256(root / "SHA256SUMS.json"),
            "supplemental_summary_sha256": direct_supplement._sha256(root / "SUMMARY.json"),
            "original_evidence_immutable": True,
        },
        "reproduce": "uv run python -m tbench.direct_supplement_finalize check",
    }


def write_report(root: Path = PAID_ROOT) -> dict[str, Any]:
    report = build_comparison_report(root)
    atomic_json(COMPARISON_REPORT_PATH, report)
    return report


def check(root: Path = PAID_ROOT) -> dict[str, Any]:
    report = build_comparison_report(root)
    if _read(COMPARISON_REPORT_PATH) != report:
        raise RuntimeError("supplemental direct-comparison report does not reproduce")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "check"))
    args = parser.parse_args()
    report = write_report() if args.command == "write" else check()
    print(
        json.dumps(
            {
                "status": report["status"],
                "post_supplement_verifier_complete_pairs": report["denominators"]["post_supplement_verifier_complete_pairs"],
                "full_ten_pair_score_available": report["full_ten_pair_score"]["available"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
