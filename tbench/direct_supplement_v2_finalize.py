"""Validate the paid Doom v2 evidence and reproduce its supplemental comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import direct_supplement_finalize, direct_supplement_v2, model_extraction_forensics
from .constants import REPOSITORY_ROOT
from .durable import atomic_json

PAID_ROOT = REPOSITORY_ROOT / "artifacts" / direct_supplement_v2.BENCHMARK_ID
ORIGINAL_REPORT_PATH = REPOSITORY_ROOT / "reports" / "direct-openai-additional-10-pairwise.json"
V1_COMPARISON_PATH = REPOSITORY_ROOT / "reports" / "direct-openai-additional-10-thinharness-supplement-v1-direct-comparison.json"
COMPARISON_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{direct_supplement_v2.BENCHMARK_ID}-direct-comparison.json"
FORENSIC_REPORT_PATH = model_extraction_forensics.REPORT_PATH
EXPECTED_USAGE = {
    "input_tokens": 6_077_818,
    "ordinary_input_tokens": 165,
    "cached_input_tokens": 5_924_686,
    "cache_write_tokens": 152_967,
    "output_tokens": 31_133,
    "reasoning_tokens": 11_192,
}
EXPECTED_COST = Decimal("4.85320175")
EXPECTED_REQUESTS = 55
EXPECTED_TOOL_CALLS = 83
_PRICE = {
    "ordinary_input_tokens": Decimal("5.0"),
    "cached_input_tokens": Decimal("0.5"),
    "cache_write_tokens": Decimal("6.25"),
    "output_tokens": Decimal("30.0"),
}


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seconds(started: str, finished: str) -> Decimal:
    start = datetime.fromisoformat(started.replace("Z", "+00:00"))
    finish = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    return Decimal(str((finish - start).total_seconds()))


def _trial(cell_dir: Path) -> Path:
    trials = [path for path in (cell_dir / "job").iterdir() if path.is_dir()]
    if len(trials) != 1:
        raise RuntimeError("paid v2 evidence must contain exactly one Harbor trial")
    return trials[0]


def _request_cost(audit: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, Decimal], Decimal]:
    usage = {name: 0 for name in EXPECTED_USAGE}
    components = {name: Decimal(0) for name in ("ordinary_input", "cached_input", "cache_write", "output")}
    mapping = {
        "ordinary_input": "ordinary_input_tokens",
        "cached_input": "cached_input_tokens",
        "cache_write": "cache_write_tokens",
        "output": "output_tokens",
    }
    for item in audit:
        item_usage = item.get("usage")
        cost = item.get("cost_usd")
        if item.get("status") != 200 or item.get("response_model") != "gpt-5.6-sol":
            raise RuntimeError("paid v2 request did not return the frozen successful model identity")
        if not isinstance(item_usage, dict) or not isinstance(cost, dict):
            raise RuntimeError("paid v2 request lacks usage or cost evidence")
        for name in usage:
            value = item_usage.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RuntimeError(f"paid v2 request has invalid usage: {name}")
            usage[name] += value
        recorded_components = cost.get("components")
        if not isinstance(recorded_components, dict):
            raise RuntimeError("paid v2 request lacks cost components")
        expected_total = Decimal(0)
        for component, token_name in mapping.items():
            expected = Decimal(item_usage[token_name]) * _PRICE[token_name] / Decimal(1_000_000)
            recorded = recorded_components.get(component)
            if not isinstance(recorded, int | float) or Decimal(str(recorded)) != expected:
                raise RuntimeError(f"paid v2 request cost component differs: {component}")
            components[component] += expected
            expected_total += expected
        recorded_total = cost.get("api_equivalent_total")
        if not isinstance(recorded_total, int | float) or abs(Decimal(str(recorded_total)) - expected_total) > Decimal("1e-15"):
            raise RuntimeError("paid v2 request API-equivalent total differs")
        if cost.get("actual_cash") is not None:
            raise RuntimeError("provider-reported paid v2 cash cost was expected to be absent")
    return usage, components, sum(components.values(), Decimal(0))


def validate_paid_evidence(root: Path = PAID_ROOT) -> dict[str, Any]:
    direct_supplement_v2.validate(root, expected_mode="real")
    direct_supplement_v2._validate_prior_evidence()
    direct_supplement_finalize.validate_paid_evidence()
    model_extraction_forensics.check()
    progress = _read(root / "progress.json")
    current_runner_identity = direct_supplement_v2._repository_identity()
    preserved_runner_identity = progress.get("runner_identity") or {}
    if (
        preserved_runner_identity.get("files") != current_runner_identity.get("files")
        or preserved_runner_identity.get("files_sha256") != current_runner_identity.get("files_sha256")
    ):
        raise RuntimeError("paid v2 model-facing runner files changed after launch")
    outcome = _read(root / "OUTCOME.json")
    summary = _read(root / "SUMMARY.json")
    published = _read(REPOSITORY_ROOT / "reports" / f"{direct_supplement_v2.BENCHMARK_ID}.json")
    cells = progress.get("cells")
    if (
        progress.get("benchmark_id") != direct_supplement_v2.BENCHMARK_ID
        or progress.get("mode") != "real"
        or progress.get("status") != "completed"
        or progress.get("planned_cells") != [direct_supplement_v2.SUPPLEMENTAL_CELL_ID]
        or not isinstance(cells, list)
        or len(cells) != 1
        or outcome.get("status") != "completed"
        or outcome.get("checkpointed_cells") != 1
        or outcome.get("planned_cells") != 1
        or summary != published
    ):
        raise RuntimeError("paid v2 finalized state differs")
    if sorted(path.name for path in (root / "cells").iterdir() if path.is_dir()) != [direct_supplement_v2.CELL_ID]:
        raise RuntimeError("paid v2 artifact contains an unauthorized cell")
    checkpoint = cells[0]
    if checkpoint != _read(root / "cells" / direct_supplement_v2.CELL_ID / "CHECKPOINT.json"):
        raise RuntimeError("paid v2 checkpoint differs from progress")
    if (
        checkpoint.get("status") != "completed"
        or checkpoint.get("reward") != 0.0
        or checkpoint.get("real_model_attempted") is not True
        or checkpoint.get("never_rerun") is not True
        or checkpoint.get("supplemental_cell_id") != direct_supplement_v2.SUPPLEMENTAL_CELL_ID
    ):
        raise RuntimeError("paid v2 outcome or consumption identity differs")
    cell_dir = root / "cells" / direct_supplement_v2.CELL_ID
    receipt = direct_supplement_v2._validate_receipt(root, checkpoint)
    audit = _jsonl(cell_dir / "gateway-audit.jsonl")
    markers = _jsonl(cell_dir / "MODEL_REQUEST_STARTED.jsonl")
    if len(audit) != EXPECTED_REQUESTS or len(markers) != EXPECTED_REQUESTS:
        raise RuntimeError("paid v2 request denominator differs")
    for sequence, (item, marker) in enumerate(zip(audit, markers, strict=True), 1):
        upstream_payload = dict(item["request"])
        upstream_payload["stream"] = False
        if (
            item.get("benchmark_id") != direct_supplement_v2.BENCHMARK_ID
            or item.get("cell_id") != direct_supplement_v2.CELL_ID
            or item.get("sequence") != sequence
            or marker.get("benchmark_id") != direct_supplement_v2.BENCHMARK_ID
            or marker.get("cell_id") != direct_supplement_v2.CELL_ID
            or marker.get("sequence") != sequence
            or marker.get("transport_retries") != 0
            or marker.get("payload_sha256") != _canonical_sha256(upstream_payload)
        ):
            raise RuntimeError("paid v2 request marker or gateway sequence differs")
    usage, components, cost = _request_cost(audit)
    if usage != EXPECTED_USAGE or cost != EXPECTED_COST:
        raise RuntimeError("paid v2 usage or API-equivalent cost differs")
    if checkpoint.get("usage") != EXPECTED_USAGE or abs(
        Decimal(str((checkpoint.get("cost") or {}).get("api_equivalent_total"))) - EXPECTED_COST
    ) > Decimal("1e-15"):
        raise RuntimeError("paid v2 checkpoint accounting differs")
    ledger = _read(root / "budget-ledger.json")
    entry = (ledger.get("cells") or {}).get(direct_supplement_v2.CELL_ID)
    if (
        not isinstance(entry, dict)
        or entry.get("consumed") is not True
        or entry.get("status") != "settled"
        or entry.get("request_count") != EXPECTED_REQUESTS
        or Decimal(str(entry.get("spent_usd"))) != EXPECTED_COST
        or Decimal(str(ledger.get("total_spent_usd"))) != EXPECTED_COST
        or ledger.get("active_cell") is not None
        or ledger.get("blocked") is not None
        or set(ledger.get("cells") or {}) != {direct_supplement_v2.CELL_ID}
    ):
        raise RuntimeError("paid v2 cap ledger differs")
    trial = _trial(cell_dir)
    harbor = _read(trial / "result.json")
    native = _read(trial / "agent" / "thinharness-direct-result.json")
    verifier = trial / "verifier"
    if (
        harbor.get("exception_info") is not None
        or harbor.get("verifier_result") != {"rewards": {"reward": 0.0}}
        or native.get("request_count") != EXPECTED_REQUESTS
        or native.get("tool_count") != EXPECTED_TOOL_CALLS
        or native.get("response_models") != ["gpt-5.6-sol"]
        or native.get("stop_reason") != "end_turn"
        or native.get("error") is not None
        or native.get("retries") != {"provider": 0, "agent_output": 0, "agent_tool": 0}
        or native.get("harness_version") != "0.7.0"
        or native.get("thinharness_commit") != "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef"
        or native.get("openai_key_in_container") is not False
        or (native.get("provider_transport") or {}).get("provider_timeout_seconds") != 1800
        or set((native.get("provider_transport") or {}).get("client_timeout_seconds", {}).values()) != {1800}
        or (native.get("process_security") or {}).get("cap_sys_ptrace") is not False
        or (native.get("process_security") or {}).get("dumpable") != 0
        or (verifier / "reward.txt").read_bytes() != b"0\n"
        or _sha256(verifier / "ctrf.json") != "95662e7063ee48fc76fcee7eb94237573cb783b961c23f0e177d483f2f639413"
    ):
        raise RuntimeError("paid v2 native, transport, security, or verifier evidence differs")
    identities = checkpoint.get("identities") or {}
    native_identity = identities.get("native_harness") or {}
    harbor_identity = identities.get("harbor") or {}
    if (
        (harbor_identity.get("task_id") or {}).get("ref") != direct_supplement_v2._cell()["task_package_digest"]
        or native_identity.get("prompt_sha256") != "bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e"
        or (native_identity.get("install") or {}).get("canonical_commit") != "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef"
        or (identities.get("gateway") or {}).get("request_retries") != 0
        or (identities.get("gateway") or {}).get("transport_retries") != 0
        or receipt.get("secret_persisted") is not False
    ):
        raise RuntimeError("paid v2 frozen task, source, prompt, retry, or credential identity differs")
    timing = checkpoint.get("timing") or {}
    return {
        "progress": progress,
        "checkpoint": checkpoint,
        "receipt": receipt,
        "audit": audit,
        "markers": markers,
        "usage": usage,
        "components": components,
        "cost": cost,
        "harbor": harbor,
        "native": native,
        "trial": trial,
        "timing": timing,
    }


def build_comparison_report(root: Path = PAID_ROOT) -> dict[str, Any]:
    paid = validate_paid_evidence(root)
    original = _read(ORIGINAL_REPORT_PATH)
    v1 = _read(V1_COMPARISON_PATH)
    pairs = original.get("paired_results")
    if not isinstance(pairs, list) or len(pairs) != 8:
        raise RuntimeError("original paired-result denominator differs")
    original_pi = sum((Decimal(str(pair["pi"]["verifier_reward"])) for pair in pairs), Decimal(0))
    original_thin = sum((Decimal(str(pair["thinharness"]["verifier_reward"])) for pair in pairs), Decimal(0))
    cells = {item["cell_id"]: item for item in original.get("cells") or []}
    doom_pi = cells["make-doom-for-mips--pi"]
    model_pi = cells["model-extraction-relu-logits--pi"]
    model_thin = cells["model-extraction-relu-logits--thinharness"]
    if (
        original_pi != Decimal(7)
        or original_thin != Decimal(7)
        or doom_pi.get("verifier_reward") != 0.0
        or model_pi.get("verifier_reward") != 1.0
        or model_thin.get("verifier_reward") is not None
    ):
        raise RuntimeError("original score or affected-task outcome differs")
    timing = paid["timing"]
    request_seconds = [Decimal(str(value)) for value in timing.get("request_seconds") or []]
    harbor = paid["harbor"]
    v1_cost = Decimal(str(v1["supplemental_paid_observation"]["cost"]["api_equivalent_usd"]))
    return {
        "schema_version": 2,
        "report_id": f"{direct_supplement_v2.BENCHMARK_ID}-direct-comparison",
        "label": "Doom-only v2 supplemental direct comparison; original and v1 evidence unchanged",
        "status": "nine_pairs_complete_one_unmatched_policy_refusal",
        "original_benchmark_id": direct_supplement_v2.direct_supplement.ORIGINAL_BENCHMARK_ID,
        "v1_supplemental_benchmark_id": direct_supplement_finalize.direct_supplement.BENCHMARK_ID,
        "v2_supplemental_benchmark_id": direct_supplement_v2.BENCHMARK_ID,
        "denominators": {
            "planned_task_pairs": 10,
            "original_verifier_complete_pairs": 8,
            "post_v2_verifier_complete_pairs": 9,
            "incomplete_pairs": 1,
            "matched_pair_policy": "include a task when Pi and the compared ThinHarness cell both have verifier outcomes",
            "v1_authorized_cells": 2,
            "v1_consumed_cells": 1,
            "v1_verifier_outcomes": 0,
            "v1_unconsumed_cells": 1,
            "v2_authorized_cells": 1,
            "v2_consumed_cells": 1,
            "v2_verifier_outcomes": 1,
            "v2_unconsumed_cells": 0,
            "remaining_authorized_future_cells": 0,
        },
        "observed_nine_pair_subset": {
            "scope": "Descriptive only; model extraction remains unmatched.",
            "denominator": 9,
            "pi_reward_sum": str(original_pi + Decimal(str(doom_pi["verifier_reward"]))),
            "thinharness_reward_sum": str(original_thin + Decimal(str(paid["checkpoint"]["reward"]))),
            "pi_minus_thinharness_reward_sum": str(
                original_pi + Decimal(str(doom_pi["verifier_reward"])) - original_thin - Decimal(str(paid["checkpoint"]["reward"]))
            ),
        },
        "full_ten_pair_score": {
            "available": False,
            "missing_tasks": ["model-extraction-relu-logits"],
            "reason": "Model extraction has no ThinHarness verifier outcome after its original and v1 policy refusals.",
        },
        "affected_tasks": {
            "make-doom-for-mips": {
                "original_pi_status": doom_pi["status"],
                "original_pi_reward": doom_pi["verifier_reward"],
                "original_thinharness_status": cells[direct_supplement_v2.CELL_ID]["status"],
                "v1_thinharness_status": "unrun_after_repeated_policy_refusal",
                "v2_thinharness_status": paid["checkpoint"]["status"],
                "v2_thinharness_reward": paid["checkpoint"]["reward"],
                "pair_included": True,
            },
            "model-extraction-relu-logits": {
                "original_pi_status": model_pi["status"],
                "original_pi_reward": model_pi["verifier_reward"],
                "original_thinharness_status": model_thin["status"],
                "v1_thinharness_status": "model_attempt_failed",
                "v2_attempt_authorized": False,
                "thinharness_verifier_outcome_available": False,
                "pair_included": False,
            },
        },
        "v2_paid_observation": {
            "cell_id": direct_supplement_v2.SUPPLEMENTAL_CELL_ID,
            "requests": EXPECTED_REQUESTS,
            "successful_requests": EXPECTED_REQUESTS,
            "tool_calls": EXPECTED_TOOL_CALLS,
            "reward": paid["checkpoint"]["reward"],
            "usage": paid["usage"],
            "cost": {
                "currency": "USD",
                "api_equivalent_usd": str(paid["cost"].quantize(Decimal("0.00000001"))),
                "provider_reported_actual_cash_usd": None,
                "components": {name: str(value.quantize(Decimal("0.00000001"))) for name, value in paid["components"].items()},
                "cap_usd": "10.00",
                "cap_breached": False,
            },
            "timing": {
                "launcher_wall_seconds": str(Decimal(str(timing["launcher_finished_at"])) - Decimal(str(timing["launcher_started_at"]))),
                "harbor_wall_seconds": str(_seconds(harbor["started_at"], harbor["finished_at"])),
                "environment_setup_seconds": str(
                    _seconds(harbor["environment_setup"]["started_at"], harbor["environment_setup"]["finished_at"])
                ),
                "agent_setup_seconds": str(_seconds(harbor["agent_setup"]["started_at"], harbor["agent_setup"]["finished_at"])),
                "agent_execution_seconds": str(_seconds(harbor["agent_execution"]["started_at"], harbor["agent_execution"]["finished_at"])),
                "native_agent_seconds": str(Decimal(str(timing["native_agent_seconds"]))),
                "request_total_seconds": str(sum(request_seconds, Decimal(0))),
                "verifier_seconds": str(_seconds(harbor["verifier"]["started_at"], harbor["verifier"]["finished_at"])),
            },
            "verifier_outcome": {"reward": 0.0},
        },
        "supplemental_costs": {
            "v1_api_equivalent_usd": str(v1_cost.quantize(Decimal("0.00000001"))),
            "v2_api_equivalent_usd": str(paid["cost"].quantize(Decimal("0.00000001"))),
            "combined_api_equivalent_usd": str((v1_cost + paid["cost"]).quantize(Decimal("0.00000001"))),
            "provider_reported_actual_cash_usd": None,
        },
        "forensic_diagnosis": {
            "report": str(FORENSIC_REPORT_PATH.relative_to(REPOSITORY_ROOT)),
            "report_sha256": _sha256(FORENSIC_REPORT_PATH),
            "diagnosis": model_extraction_forensics.build_report()["findings"]["diagnosis"],
            "confidence": model_extraction_forensics.build_report()["findings"]["confidence"],
        },
        "evidence": {
            "original_report": str(ORIGINAL_REPORT_PATH.relative_to(REPOSITORY_ROOT)),
            "original_report_sha256": _sha256(ORIGINAL_REPORT_PATH),
            "v1_comparison_report": str(V1_COMPARISON_PATH.relative_to(REPOSITORY_ROOT)),
            "v1_comparison_report_sha256": _sha256(V1_COMPARISON_PATH),
            "v2_artifact": str(root.relative_to(REPOSITORY_ROOT)),
            "v2_sha256_manifest": str((root / "SHA256SUMS.json").relative_to(REPOSITORY_ROOT)),
            "v2_sha256_manifest_sha256": _sha256(root / "SHA256SUMS.json"),
            "v2_summary_sha256": _sha256(root / "SUMMARY.json"),
            "original_and_v1_evidence_immutable": True,
        },
        "reproduce": "uv run python -m tbench.direct_supplement_v2_finalize check",
    }


def write_report(root: Path = PAID_ROOT) -> dict[str, Any]:
    report = build_comparison_report(root)
    atomic_json(COMPARISON_REPORT_PATH, report)
    return report


def check(root: Path = PAID_ROOT) -> dict[str, Any]:
    report = build_comparison_report(root)
    if _read(COMPARISON_REPORT_PATH) != report:
        raise RuntimeError("v2 supplemental direct-comparison report does not reproduce")
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
                "post_v2_verifier_complete_pairs": report["denominators"]["post_v2_verifier_complete_pairs"],
                "pi_reward_sum": report["observed_nine_pair_subset"]["pi_reward_sum"],
                "thinharness_reward_sum": report["observed_nine_pair_subset"]["thinharness_reward_sum"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
