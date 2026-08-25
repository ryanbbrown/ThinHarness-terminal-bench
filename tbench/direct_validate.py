"""Artifact validation and reporting for the direct-OpenAI pairwise run."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .direct_constants import (
    EXPECTED_CELLS,
    MODEL,
    PI_SCHEMAS_PATH,
    PI_VERSION,
    PREFLIGHT_REPORT_PATH,
    PRICES,
    REPORT_PATH,
    SELECTION_PATH,
    SETTINGS_PATH,
    THIN_SCHEMAS_PATH,
    THINHARNESS_COMMIT,
    THINHARNESS_VERSION,
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON receipt is not an object: {path}")
    return value


def _audit(path: Path) -> list[dict[str, Any]]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise RuntimeError(f"gateway audit line is not an object: {path}")
        values.append(value)
    return values


def _trial(cell_dir: Path) -> Path:
    job = cell_dir / "job"
    trials = [path for path in job.iterdir() if path.is_dir()]
    if len(trials) != 1:
        raise RuntimeError(f"expected one Harbor trial in {job}, found {len(trials)}")
    return trials[0]


def _receipt(trial: Path, harness: str) -> dict[str, Any]:
    return _read_json(trial / "agent" / f"{harness}-direct-result.json")


def _selection_map() -> dict[str, dict[str, Any]]:
    return {item["task"]: item for item in _read_json(SELECTION_PATH)["selected"]}


def _verifier_evidence(trial: Path) -> Path:
    candidates = (trial / "verifier" / "ctrf.json", trial / "verifier" / "reward.txt")
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError(f"verifier evidence is absent in {trial}")


def _audit_outcome(audit: list[dict[str, Any]], *, mode: str, cell_id: str) -> str:
    if not audit:
        raise RuntimeError(f"gateway audit is empty for {cell_id}")
    outcome = "completed"
    for sequence, item in enumerate(audit, 1):
        if item.get("cell_id") != cell_id or item.get("sequence") != sequence:
            raise RuntimeError(f"gateway audit sequence failed for {cell_id}")
        status = item.get("status")
        if status == 200:
            if outcome != "completed":
                raise RuntimeError(f"gateway audit continues after a final error for {cell_id}")
            if item.get("response_model") != MODEL or not isinstance(item.get("usage"), dict) or not isinstance(item.get("cost_usd"), dict):
                raise RuntimeError(f"gateway response identity or accounting is incomplete for {cell_id}")
            continue
        error = (item.get("response") or {}).get("error")
        if (
            mode != "real"
            or sequence != len(audit)
            or not isinstance(status, int)
            or status < 400
            or not isinstance(error, dict)
            or not isinstance(error.get("type"), str)
            or item.get("response_model") is not None
            or item.get("usage") is not None
            or item.get("cost_usd") is not None
        ):
            raise RuntimeError(f"gateway terminal error evidence is invalid for {cell_id}")
        outcome = "credit_exhausted" if item.get("credit_exhausted") is True else "model_attempt_failed"
    return outcome


def validate_cell(cell_dir: Path, *, mode: str, cell_id: str) -> dict[str, Any]:
    """Validate one completed Harbor cell and all native-interface receipts."""
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    task, harness = cell_id.rsplit("--", 1)
    if harness not in {"pi", "thinharness"}:
        raise RuntimeError(f"unknown harness in cell: {cell_id}")
    if cell_id not in EXPECTED_CELLS:
        raise RuntimeError(f"cell is not in the frozen order: {cell_id}")
    launch = _read_json(cell_dir / "launch.json")
    gateway = _read_json(cell_dir / "gateway-identity.json")
    audit = _audit(cell_dir / "gateway-audit.jsonl")
    if launch.get("cell_id") != cell_id or launch.get("mode") != mode or launch.get("harness") != harness:
        raise RuntimeError(f"launch identity differs for {cell_id}")
    if gateway.get("cell_id") != cell_id or gateway.get("mode") != mode or gateway.get("bridge") is not None:
        raise RuntimeError(f"gateway identity differs for {cell_id}")
    if mode == "fake":
        if (cell_dir / "MODEL_REQUEST_STARTED.jsonl").exists() or gateway.get("upstream") is not None or len(audit) != 2:
            raise RuntimeError(f"fake cell does not prove zero upstream requests: {cell_id}")
    else:
        marker_path = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
        if not marker_path.is_file() or gateway.get("direct_openai") is not True:
            raise RuntimeError(f"real cell does not prove direct OpenAI routing: {cell_id}")
        markers = _audit(marker_path)
        if len(markers) != len(audit) or any(
            item.get("cell_id") != cell_id or item.get("sequence") != sequence
            for sequence, item in enumerate(markers, 1)
        ):
            raise RuntimeError(f"model-request markers differ from the gateway audit for {cell_id}")
    outcome = _audit_outcome(audit, mode=mode, cell_id=cell_id)
    credit_marker = (cell_dir / "CREDIT_EXHAUSTED.json").is_file()
    if (outcome == "credit_exhausted") != credit_marker:
        raise RuntimeError(f"credit-exhaustion evidence differs for {cell_id}")
    trial = _trial(cell_dir)
    result = _read_json(trial / "result.json")
    receipt = _receipt(trial, harness)
    selected = _selection_map()[task]
    task_id = result.get("task_id") or {}
    if task_id.get("name") != task or task_id.get("ref") != selected["task_package_digest"]:
        raise RuntimeError(f"Harbor task package identity differs for {cell_id}")
    if result.get("exception_info") is not None:
        raise RuntimeError(f"Harbor reports an exception for {cell_id}")
    if receipt.get("cell_id") != cell_id or receipt.get("mode") != mode or receipt.get("model") != MODEL:
        raise RuntimeError(f"native receipt identity differs for {cell_id}")
    if receipt.get("prompt_sha256") != _read_json(SETTINGS_PATH)["prompt"]["sha256"]:
        raise RuntimeError(f"prompt identity differs for {cell_id}")
    if receipt.get("openai_key_in_container") is not False:
        raise RuntimeError(f"credential isolation is not proved for {cell_id}")
    successful_models = sorted(
        {model for item in audit if item.get("status") == 200 and isinstance(model := item.get("response_model"), str)}
    )
    if receipt.get("response_models") != successful_models or receipt.get("request_count") != len(audit):
        raise RuntimeError(f"native request identity differs from gateway trace for {cell_id}")
    if harness == "pi":
        frozen_pi = _read_json(PI_SCHEMAS_PATH)
        expected_pi_tools = {"root": frozen_pi["root"], "tools": frozen_pi["tools"]}
        if receipt.get("harness_version") != PI_VERSION or receipt.get("tools") != expected_pi_tools:
            raise RuntimeError(f"Pi version or native tool schemas differ for {cell_id}")
    else:
        install = receipt.get("install") or {}
        if (
            receipt.get("harness_version") != THINHARNESS_VERSION
            or receipt.get("thinharness_commit") != THINHARNESS_COMMIT
            or install.get("canonical_commit") != THINHARNESS_COMMIT
            or receipt.get("tool_schemas") != _read_json(THIN_SCHEMAS_PATH)["schemas"]
            or (receipt.get("provider_transport") or {}).get("provider_owns_client") is not True
        ):
            raise RuntimeError(f"ThinHarness identity, timeout ownership, or native schemas differ for {cell_id}")
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    if not isinstance(reward, int | float):
        raise RuntimeError(f"verifier reward is absent for {cell_id}")
    if mode == "fake" and reward != 0:
        raise RuntimeError(f"controlled unsolved fake cell unexpectedly passed: {cell_id}")
    _verifier_evidence(trial)
    return cell_summary(cell_dir, status=outcome, real_model_attempted=mode == "real")


def recover_consumed_cell(cell_dir: Path, *, mode: str, cell_id: str) -> dict[str, Any]:
    """Build a final checkpoint for an interrupted cell that started a real request."""
    marker = cell_dir / "MODEL_REQUEST_STARTED.jsonl"
    if mode != "real" or not marker.is_file() or not marker.stat().st_size:
        raise RuntimeError(f"cell has no consumed real model attempt: {cell_id}")
    launch = _read_json(cell_dir / "launch.json")
    if launch.get("cell_id") != cell_id or launch.get("mode") != mode:
        raise RuntimeError(f"launch identity differs for recovered cell {cell_id}")
    try:
        return validate_cell(cell_dir, mode=mode, cell_id=cell_id)
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        status = "credit_exhausted" if (cell_dir / "CREDIT_EXHAUSTED.json").is_file() else "consumed_interrupted"
        checkpoint = cell_summary(cell_dir, status=status, real_model_attempted=True)
        checkpoint["recovery_validation_error"] = {"type": type(exc).__name__, "message": str(exc)}
        return checkpoint


def _usage_and_cost(audit: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, Any]]:
    usage = {
        "input_tokens": 0,
        "ordinary_input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    components = {name: 0.0 for name in PRICES}
    actual: list[float] = []
    successful_requests = 0
    for item in audit:
        for name in usage:
            value = (item.get("usage") or {}).get(name)
            if isinstance(value, int):
                usage[name] += value
        cost = item.get("cost_usd") or {}
        if item.get("status") == 200:
            successful_requests += 1
        for name in components:
            value = (cost.get("components") or {}).get(name)
            if isinstance(value, int | float):
                components[name] += float(value)
        if isinstance(cost.get("actual_cash"), int | float):
            actual.append(float(cost["actual_cash"]))
    return usage, {
        "currency": "USD",
        "components": components,
        "api_equivalent_total": sum(components.values()),
        "actual_cash_total": sum(actual) if len(actual) == successful_requests and successful_requests else None,
        "prices_usd_per_million_tokens": PRICES,
    }


def cell_summary(cell_dir: Path, *, status: str, real_model_attempted: bool) -> dict[str, Any]:
    """Build the durable per-cell checkpoint from all evidence available."""
    launch = _read_json(cell_dir / "launch.json")
    audit_path = cell_dir / "gateway-audit.jsonl"
    audit = _audit(audit_path) if audit_path.is_file() else []
    usage, cost = _usage_and_cost(audit)
    result: dict[str, Any] = {}
    receipt: dict[str, Any] = {}
    gateway: dict[str, Any] = {}
    trial: Path | None = None
    try:
        gateway = _read_json(cell_dir / "gateway-identity.json")
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError):
        pass
    try:
        trial = _trial(cell_dir)
        result = _read_json(trial / "result.json")
        receipt = _receipt(trial, str(launch.get("harness")))
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError):
        pass
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    successful_requests = [item for item in audit if item.get("status") == 200]
    terminal_error = next((item for item in reversed(audit) if item.get("status") != 200), None)
    batching = []
    for item in audit:
        output = (item.get("response") or {}).get("output") or []
        names = [entry.get("name") for entry in output if isinstance(entry, dict) and entry.get("type") == "function_call"]
        batching.append({"sequence": item.get("sequence"), "tool_calls_in_response": len(names), "tool_names": names})
    verifier = None
    if trial is not None:
        try:
            verifier = _verifier_evidence(trial)
        except RuntimeError:
            pass
    return {
        "schema_version": 1,
        "cell_id": launch.get("cell_id"),
        "task": launch.get("task"),
        "harness": launch.get("harness"),
        "mode": launch.get("mode"),
        "status": status,
        "real_model_attempted": real_model_attempted,
        "never_rerun": real_model_attempted,
        "restart_action": (
            "never rerun; continue to the next frozen cell" if real_model_attempted else "recoverable before any model request"
        ),
        "harbor_exit_code": launch.get("harbor_exit_code"),
        "request_count": len(audit),
        "successful_request_count": len(successful_requests),
        "usage": usage,
        "cost": cost,
        "reward": reward,
        "verifier_outcome": result.get("verifier_result"),
        "model_attempt_failure": (
            {
                "sequence": terminal_error.get("sequence"),
                "status": terminal_error.get("status"),
                "credit_exhausted": terminal_error.get("credit_exhausted"),
                "response": terminal_error.get("response"),
                "response_sha256": terminal_error.get("response_sha256"),
                "response_headers": terminal_error.get("response_headers"),
            }
            if terminal_error is not None
            else None
        ),
        "timing": {
            "launcher_started_at": launch.get("started_at"),
            "launcher_finished_at": launch.get("finished_at"),
            "harbor_started_at": result.get("started_at"),
            "harbor_finished_at": result.get("finished_at"),
            "environment_setup": result.get("environment_setup"),
            "agent_setup": result.get("agent_setup"),
            "agent_execution": result.get("agent_execution"),
            "native_agent_seconds": receipt.get("agent_seconds"),
            "verifier": result.get("verifier"),
            "request_seconds": [item.get("duration_seconds") for item in audit],
        },
        "batching": batching,
        "traces": {
            "model_request_markers": (
                str((cell_dir / "MODEL_REQUEST_STARTED.jsonl").relative_to(cell_dir.parent.parent))
                if (cell_dir / "MODEL_REQUEST_STARTED.jsonl").is_file()
                else None
            ),
            "gateway_audit": str(audit_path.relative_to(cell_dir.parent.parent)) if audit_path.is_file() else None,
            "gateway_identity": (
                str((cell_dir / "gateway-identity.json").relative_to(cell_dir.parent.parent))
                if (cell_dir / "gateway-identity.json").is_file()
                else None
            ),
            "launch": str((cell_dir / "launch.json").relative_to(cell_dir.parent.parent)),
            "native_receipt": (
                str((trial / "agent" / f"{launch.get('harness')}-direct-result.json").relative_to(cell_dir.parent.parent))
                if trial is not None and (trial / "agent" / f"{launch.get('harness')}-direct-result.json").is_file()
                else None
            ),
            "native_events": (
                str((trial / "agent" / f"{launch.get('harness')}-events.jsonl").relative_to(cell_dir.parent.parent))
                if trial is not None and (trial / "agent" / f"{launch.get('harness')}-events.jsonl").is_file()
                else None
            ),
            "native_stderr": (
                str((trial / "agent" / f"{launch.get('harness')}-stderr.log").relative_to(cell_dir.parent.parent))
                if trial is not None and (trial / "agent" / f"{launch.get('harness')}-stderr.log").is_file()
                else None
            ),
            "harbor_result": (
                str((trial / "result.json").relative_to(cell_dir.parent.parent))
                if trial is not None and (trial / "result.json").is_file()
                else None
            ),
            "verifier_evidence": str(verifier.relative_to(cell_dir.parent.parent)) if verifier is not None else None,
            "verifier_evidence_type": verifier.name if verifier is not None else None,
            "verifier_evidence_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest() if verifier is not None else None,
            "staging_stdout": str((cell_dir / "harbor.stdout.log").relative_to(cell_dir.parent.parent)),
            "staging_stderr": str((cell_dir / "harbor.stderr.log").relative_to(cell_dir.parent.parent)),
        },
        "identities": {
            "runner": launch.get("runner_identity"),
            "launch_gateway": launch.get("gateway"),
            "gateway": gateway,
            "source_bundle_sha256": launch.get("source_bundle_sha256"),
            "model": {
                "name": receipt.get("model") or MODEL,
                "backend": receipt.get("backend"),
                "reasoning": receipt.get("reasoning"),
                "text": receipt.get("text"),
                "response_models": receipt.get("response_models"),
            },
            "native_harness": {
                "kind": receipt.get("kind"),
                "cell_id": receipt.get("cell_id"),
                "mode": receipt.get("mode"),
                "harness": receipt.get("harness"),
                "harness_version": receipt.get("harness_version"),
                "thinharness_commit": receipt.get("thinharness_commit"),
                "prompt_sha256": receipt.get("prompt_sha256"),
                "install": receipt.get("install"),
                "execution": receipt.get("execution"),
                "tools": receipt.get("tools"),
                "tool_schemas": receipt.get("tool_schemas"),
                "provider_transport": receipt.get("provider_transport"),
            },
            "harbor": {
                "id": result.get("id"),
                "task_name": result.get("task_name"),
                "trial_name": result.get("trial_name"),
                "task_id": result.get("task_id"),
                "task_checksum": result.get("task_checksum"),
                "source": result.get("source"),
                "agent_info": result.get("agent_info"),
            },
        },
    }


def build_report(root: Path) -> dict[str, Any]:
    progress = _read_json(root / "progress.json")
    cells = progress.get("cells") or []
    usage_names = (
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    totals_usage = {name: 0 for name in usage_names}
    total_cost = 0.0
    total_requests = 0
    successful_requests = 0
    status_counts: dict[str, int] = {}
    rewards = []
    for cell in cells:
        for name in totals_usage:
            value = (cell.get("usage") or {}).get(name)
            if isinstance(value, int):
                totals_usage[name] += value
        value = (cell.get("cost") or {}).get("api_equivalent_total")
        if isinstance(value, int | float):
            total_cost += float(value)
        if isinstance(cell.get("request_count"), int):
            total_requests += cell["request_count"]
        if isinstance(cell.get("successful_request_count"), int):
            successful_requests += cell["successful_request_count"]
        elif cell.get("status") == "completed" and isinstance(cell.get("request_count"), int):
            successful_requests += cell["request_count"]
        cell_status = cell.get("status")
        if isinstance(cell_status, str):
            status_counts[cell_status] = status_counts.get(cell_status, 0) + 1
        if isinstance(cell.get("reward"), int | float):
            rewards.append(float(cell["reward"]))
    return {
        "schema_version": 1,
        "benchmark_id": progress.get("benchmark_id"),
        "mode": progress.get("mode"),
        "status": progress.get("status"),
        "dataset": progress.get("dataset"),
        "model": progress.get("model"),
        "planned_cells": len(EXPECTED_CELLS),
        "checkpointed_cells": len(cells),
        "cells": cells,
        "aggregate": {
            "usage": totals_usage,
            "api_equivalent_cost_usd": total_cost,
            "request_count": total_requests,
            "successful_request_count": successful_requests,
            "cell_status_counts": status_counts,
            "reward_sum": sum(rewards),
            "reward_count": len(rewards),
        },
        "runner_identity": progress.get("runner_identity"),
        "source_bundle_sha256": progress.get("source_bundle_sha256"),
        "stop": progress.get("stop"),
    }


def write_report(root: Path) -> dict[str, Any]:
    report = build_report(root)
    content = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (root / "SUMMARY.json").write_text(content, encoding="utf-8")
    target = PREFLIGHT_REPORT_PATH if report.get("mode") == "fake" else REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return report


def write_hashes(root: Path) -> dict[str, str]:
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    (root / "SHA256SUMS.json").write_text(json.dumps(hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hashes


def validate_hashes(root: Path) -> None:
    expected = _read_json(root / "SHA256SUMS.json")
    actual = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.json"
    }
    if actual != expected:
        raise RuntimeError("artifact SHA256 manifest differs from durable files")


def validate_finalized_preflight(root: Path) -> dict[str, Any]:
    report = _read_json(root / "SUMMARY.json")
    if report.get("mode") != "fake" or report.get("status") != "completed" or report.get("checkpointed_cells") != 40:
        raise RuntimeError("complete 40-cell no-model preflight is absent")
    if [cell.get("cell_id") for cell in report.get("cells") or []] != list(EXPECTED_CELLS):
        raise RuntimeError("preflight cell order differs from the frozen order")
    for cell_id in EXPECTED_CELLS:
        validate_cell(root / "cells" / cell_id, mode="fake", cell_id=cell_id)
    validate_hashes(root)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--copy-report", type=Path)
    args = parser.parse_args()
    report = validate_finalized_preflight(args.root) if args.preflight else build_report(args.root)
    if args.copy_report:
        args.copy_report.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.root / "SUMMARY.json", args.copy_report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
