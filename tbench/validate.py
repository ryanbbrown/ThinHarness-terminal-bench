"""Independent receipt checks for no-model and paid Harbor runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import (
    AGENT_OUTPUT_RETRIES,
    AGENT_TOOL_RETRIES,
    ATTEMPT_BUDGET_USD,
    CONTAINER_ROOT,
    DATASET_DIGEST,
    IMPLEMENTATION_BUDGET_USD,
    MODEL_ID,
    OPENAI_BASE_URL,
    PROMPT_PATH,
    PROMPT_SHA256,
    PROVIDER_RETRIES,
    REASONING,
    REPOSITORY_ROOT,
    TASK_NAME,
    TEXT,
    THINHARNESS_COMMIT,
)

_PAID_RUN_REPOSITORY_COMMIT = "aeb3ebad41e993633d6fb6463bc155edbacff0e7"
_PAID_USAGE_FIELDS = (
    "input_tokens",
    "ordinary_input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
)


class ValidationError(RuntimeError):
    """A durable receipt does not prove the required claim."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError(f"JSON receipt is not an object: {path}")
    return value


def validate_container_preflight(path: Path) -> dict[str, Any]:
    """Validate native plugins, schemas, roots, pins, and zero-call execution."""
    value = _read(path)
    _equal(value.get("kind"), "no-model-container-preflight", "preflight kind")
    _equal(value.get("model_calls"), 0, "model calls")
    _equal(value.get("passed"), True, "preflight result")
    _equal(value.get("root"), CONTAINER_ROOT, "harness root")
    _equal(value.get("execution", {}).get("execution"), "harbor-task-container", "execution location")
    _equal(value.get("execution", {}).get("cwd"), CONTAINER_ROOT, "process cwd")
    _equal(value.get("thinharness", {}).get("canonical_commit"), THINHARNESS_COMMIT, "ThinHarness commit")
    _equal(value.get("thinharness", {}).get("install", {}).get("canonical_commit"), THINHARNESS_COMMIT, "wheel source commit")
    _equal(value.get("prompt", {}).get("sha256"), PROMPT_SHA256, "prompt hash")
    _equal(hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest(), PROMPT_SHA256, "repository prompt hash")
    staged = value.get("staged_control_sha256")
    control_paths = {
        "budget.py": REPOSITORY_ROOT / "tbench" / "budget.py",
        "constants.py": REPOSITORY_ROOT / "tbench" / "constants.py",
        "container_runner.py": REPOSITORY_ROOT / "tbench" / "container_runner.py",
        "container-runtime-requirements.txt": REPOSITORY_ROOT / "configs" / "container-runtime-requirements.txt",
        "install-in-container.sh": REPOSITORY_ROOT / "scripts" / "install-in-container.sh",
        "system-prompt.md": PROMPT_PATH,
    }
    expected_controls = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in control_paths.items()}
    _equal(staged, expected_controls, "staged control hashes")
    tools = value.get("tools", {})
    if set(tools.get("names", [])) != {"bash", "read", "edit", "write"}:
        raise ValidationError("native tool names differ")
    expected_plugins = {"bash": "bash", "read": "filesystem", "edit": "filesystem", "write": "filesystem"}
    if {name: item.get("plugin") for name, item in tools.get("origins", {}).items()} != expected_plugins:
        raise ValidationError("tool origins are not native plugins")
    schemas = tools.get("schemas")
    if not isinstance(schemas, list) or len(schemas) != 4:
        raise ValidationError("tool schema receipt is incomplete")
    for schema in schemas:
        if not isinstance(schema, dict) or schema.get("type") != "function" or not isinstance(schema.get("parameters"), dict):
            raise ValidationError("tool schema is not a complete Responses function schema")
    wire = value.get("wire", {})
    for actual, expected, label in (
        (wire.get("base_url"), OPENAI_BASE_URL, "base URL"),
        (wire.get("model"), MODEL_ID, "model"),
        (wire.get("reasoning"), REASONING, "reasoning"),
        (wire.get("text"), TEXT, "text"),
        (wire.get("provider_retries"), PROVIDER_RETRIES, "provider retries"),
        (wire.get("agent_output_retries"), AGENT_OUTPUT_RETRIES, "output retries"),
        (wire.get("agent_tool_retries"), AGENT_TOOL_RETRIES, "tool retries"),
        (wire.get("payload_probe", {}).get("model"), MODEL_ID, "payload model"),
        (wire.get("payload_probe", {}).get("reasoning"), REASONING, "payload reasoning"),
        (wire.get("payload_probe", {}).get("text"), TEXT, "payload text"),
        (wire.get("payload_probe", {}).get("network_requests"), 0, "payload probe network requests"),
    ):
        _equal(actual, expected, label)
    _equal(value.get("verifier_handoff", {}).get("harbor_owns_verifier"), True, "verifier ownership")
    return value


def validate_paid_job(job_dir: Path) -> dict[str, Any]:
    """Require a verifier pass and reconcile the native agent and API ledger receipts."""
    agent_paths = list(job_dir.glob("**/agent/native-thinharness-result.json"))
    trial_paths = [path for path in job_dir.glob("**/result.json") if path.parent != job_dir]
    if len(agent_paths) != 1 or len(trial_paths) != 1:
        raise ValidationError("paid job must contain exactly one agent and one trial receipt")
    agent = _read(agent_paths[0])
    trial = _read(trial_paths[0])
    _equal(agent.get("kind"), "paid-native-thinharness-attempt", "agent receipt kind")
    _equal(agent.get("task"), TASK_NAME, "task")
    _equal(agent.get("dataset_digest"), DATASET_DIGEST, "dataset digest")
    _equal(agent.get("thinharness", {}).get("canonical_commit"), THINHARNESS_COMMIT, "ThinHarness commit")
    _equal(agent.get("execution", {}).get("execution"), "harbor-task-container", "execution location")
    _equal(agent.get("root"), CONTAINER_ROOT, "root")
    _equal(agent.get("response_models"), [MODEL_ID], "response identity")
    _equal(agent.get("stop_reason"), "end_turn", "stop reason")
    ledger = agent.get("api_budget")
    if not isinstance(ledger, dict):
        raise ValidationError("API budget receipt is absent")
    _equal(ledger.get("status"), "completed", "ledger status")
    _equal(ledger.get("in_flight_request_id"), None, "in-flight request")
    spent = ledger.get("spent_usd")
    if isinstance(spent, bool) or not isinstance(spent, int | float) or spent > ATTEMPT_BUDGET_USD + 1e-9:
        raise ValidationError("attempt spend exceeds USD 0.50")
    if ledger.get("prior_implementation_spend_usd", 0) + spent > IMPLEMENTATION_BUDGET_USD + 1e-9:
        raise ValidationError("implementation spend exceeds USD 1.00")
    requests = ledger.get("requests")
    if not isinstance(requests, list) or not requests or any(request.get("status") != "completed" for request in requests):
        raise ValidationError("request receipts are incomplete")
    for request in requests:
        usage = request.get("usage")
        required = {
            "input_tokens",
            "ordinary_input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
        }
        if not isinstance(usage, dict) or set(usage) != required:
            raise ValidationError("request token classes are incomplete")
    verifier_result = trial.get("verifier_result") or {}
    rewards = verifier_result.get("rewards") or {}
    reward = rewards.get("reward", trial.get("reward"))
    if reward != 1 and reward != 1.0:
        raise ValidationError(f"Terminal-Bench verifier did not pass: {reward!r}")
    times = {
        "started_at": trial.get("started_at"),
        "finished_at": trial.get("finished_at"),
        "agent_execution": trial.get("agent_execution"),
        "verifier": trial.get("verifier"),
    }
    report = {
        "schema_version": 1,
        "passed": True,
        "reward": reward,
        "task": TASK_NAME,
        "agent_receipt": str(agent_paths[0]),
        "trial_receipt": str(trial_paths[0]),
        "api_equivalent_cost_usd": spent,
        "actual_cash_cost_usd": agent.get("actual_cash_cost_usd"),
        "requests": len(requests),
        "tokens": agent.get("usage"),
        "tool_names": agent.get("tool_names"),
        "agent_time_seconds": agent.get("agent_time_seconds"),
        "harbor_timing": times,
        "thinharness_commit": THINHARNESS_COMMIT,
        "environment": agent.get("execution"),
        "prompt_sha256": PROMPT_SHA256,
    }
    return report


def validate_paid_artifacts(artifact_dir: Path) -> dict[str, Any]:
    """Validate immutable paid receipts and return a durable-path E2E report."""
    required_files = {
        "api-budget.json",
        "container-preflight.json",
        "harbor-config.json",
        "harbor-lock.json",
        "host-agent-setup.json",
        "implementation-budget.json",
        "job-result.json",
        "launch.json",
        "native-thinharness-result.json",
        "PROVENANCE.md",
        "trial-lock.json",
        "trial-result.json",
        "verifier-ctrf.json",
        "verifier-reward.txt",
    }
    hashes = _read(artifact_dir / "SHA256SUMS.json")
    _equal(hashes.get("algorithm"), "sha256", "receipt hash algorithm")
    recorded_hashes = hashes.get("files")
    if not isinstance(recorded_hashes, dict) or set(recorded_hashes) != required_files:
        raise ValidationError("paid receipt hash manifest has an unexpected file set")
    for name, expected_hash in recorded_hashes.items():
        path = artifact_dir / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise ValidationError(f"paid receipt hash differs: {name}")

    preflight = validate_container_preflight(artifact_dir / "container-preflight.json")
    agent = _read(artifact_dir / "native-thinharness-result.json")
    ledger = _read(artifact_dir / "api-budget.json")
    trial = _read(artifact_dir / "trial-result.json")
    harbor_config = _read(artifact_dir / "harbor-config.json")
    harbor_lock = _read(artifact_dir / "harbor-lock.json")
    trial_lock = _read(artifact_dir / "trial-lock.json")
    launch = _read(artifact_dir / "launch.json")
    implementation_budget = _read(artifact_dir / "implementation-budget.json")
    job_result = _read(artifact_dir / "job-result.json")
    verifier = _read(artifact_dir / "verifier-ctrf.json")

    _equal(agent.get("api_budget"), ledger, "standalone and embedded API ledgers")
    _equal(agent.get("kind"), "paid-native-thinharness-attempt", "paid receipt kind")
    _equal(agent.get("task"), TASK_NAME, "paid task")
    _equal(agent.get("dataset_digest"), DATASET_DIGEST, "paid dataset digest")
    _equal(agent.get("root"), CONTAINER_ROOT, "paid harness root")
    _equal(agent.get("response_models"), [MODEL_ID], "paid response model")
    _equal(agent.get("stop_reason"), "end_turn", "paid stop reason")
    _equal(agent.get("error"), None, "paid agent error")
    _equal(agent.get("prompt_sha256"), PROMPT_SHA256, "paid prompt hash")
    _equal(agent.get("staged_control_sha256"), preflight.get("staged_control_sha256"), "paid staged controls")
    _equal(agent.get("thinharness", {}).get("canonical_commit"), THINHARNESS_COMMIT, "paid ThinHarness commit")
    wheel_sha256 = agent.get("thinharness", {}).get("install", {}).get("wheel_sha256")
    if not isinstance(wheel_sha256, str) or len(wheel_sha256) != 64:
        raise ValidationError("paid wheel identity is missing")
    _equal(agent.get("execution", {}).get("execution"), "harbor-task-container", "paid execution location")
    _equal(agent.get("execution", {}).get("cwd"), CONTAINER_ROOT, "paid execution cwd")

    _equal(ledger.get("status"), "completed", "paid ledger status")
    _equal(ledger.get("fatal_error"), None, "paid ledger fatal error")
    _equal(ledger.get("in_flight_request_id"), None, "paid in-flight request")
    _equal(ledger.get("reserved_usd"), 0.0, "paid reserved spend")
    requests = ledger.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValidationError("paid request receipts are missing")
    totals = {field: 0 for field in _PAID_USAGE_FIELDS}
    request_cost = 0.0
    reported_cash_values: list[float | None] = []
    for request in requests:
        if not isinstance(request, dict) or request.get("status") != "completed":
            raise ValidationError("paid request receipt is incomplete")
        _equal(request.get("response_model"), MODEL_ID, "request response model")
        usage = request.get("usage")
        if not isinstance(usage, dict) or set(usage) != set(_PAID_USAGE_FIELDS):
            raise ValidationError("paid request token classes are incomplete")
        for field in _PAID_USAGE_FIELDS:
            value = usage[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError(f"paid request has invalid {field}")
            totals[field] += value
        _equal(
            usage["input_tokens"],
            usage["ordinary_input_tokens"] + usage["cached_input_tokens"] + usage["cache_write_tokens"],
            "request input token reconciliation",
        )
        cost = request.get("api_equivalent_cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, int | float) or cost < 0:
            raise ValidationError("paid request API-equivalent cost is invalid")
        request_cost += float(cost)
        cash = request.get("reported_cash_cost_usd")
        if cash is not None and (isinstance(cash, bool) or not isinstance(cash, int | float) or cash < 0):
            raise ValidationError("paid request cash cost is invalid")
        reported_cash_values.append(float(cash) if isinstance(cash, int | float) and not isinstance(cash, bool) else None)
    spent = ledger.get("spent_usd")
    if isinstance(spent, bool) or not isinstance(spent, int | float):
        raise ValidationError("paid spend is invalid")
    if abs(request_cost - float(spent)) > 1e-12:
        raise ValidationError("request costs do not reconcile with paid spend")
    if spent > ATTEMPT_BUDGET_USD + 1e-9:
        raise ValidationError("paid spend exceeds the attempt ceiling")
    if ledger.get("prior_implementation_spend_usd", 0) + spent > IMPLEMENTATION_BUDGET_USD + 1e-9:
        raise ValidationError("paid spend exceeds the implementation ceiling")
    actual_cash_cost = None if all(value is None for value in reported_cash_values) else sum(
        value for value in reported_cash_values if value is not None
    )
    if any(value is None for value in reported_cash_values) and actual_cash_cost is not None:
        raise ValidationError("cash cost is only partially reported")
    _equal(agent.get("actual_cash_cost_usd"), actual_cash_cost, "agent cash cost")
    _equal(agent.get("api_equivalent_cost_usd"), spent, "agent API-equivalent cost")

    agent_usage = agent.get("usage") or {}
    _equal(agent_usage.get("input_tokens"), totals["input_tokens"], "agent input tokens")
    _equal(agent_usage.get("cached_tokens"), totals["cached_input_tokens"], "agent cached tokens")
    _equal(agent_usage.get("output_tokens"), totals["output_tokens"], "agent output tokens")
    _equal(agent_usage.get("model_requests"), len(requests), "agent request count")
    tool_names = agent.get("tool_names")
    if not isinstance(tool_names, list) or not all(isinstance(name, str) for name in tool_names):
        raise ValidationError("paid tool names are invalid")
    _equal(agent_usage.get("tool_calls"), len(tool_names), "paid tool count")
    _equal(len(agent.get("tool_call_records") or []), len(tool_names), "paid tool records")

    reward = (trial.get("verifier_result") or {}).get("rewards", {}).get("reward")
    _equal(reward, 1.0, "paid verifier reward")
    try:
        reward_file = float((artifact_dir / "verifier-reward.txt").read_text(encoding="utf-8").strip())
    except ValueError as exc:
        raise ValidationError("verifier reward file is invalid") from exc
    _equal(reward_file, reward, "verifier reward file")
    summary = (verifier.get("results") or {}).get("summary") or {}
    _equal(summary.get("tests"), 1, "verifier test count")
    _equal(summary.get("passed"), 1, "verifier passed count")
    _equal(summary.get("failed"), 0, "verifier failed count")
    _equal(trial.get("exception_info"), None, "paid trial exception")
    _equal((trial.get("agent_result") or {}).get("n_input_tokens"), totals["input_tokens"], "Harbor input tokens")
    _equal((trial.get("agent_result") or {}).get("n_cache_tokens"), totals["cached_input_tokens"], "Harbor cached tokens")
    _equal((trial.get("agent_result") or {}).get("n_output_tokens"), totals["output_tokens"], "Harbor output tokens")

    _equal(harbor_lock.get("harbor", {}).get("version"), "0.21.0", "Harbor version")
    _equal(harbor_lock.get("retry", {}).get("max_retries"), 0, "Harbor retries")
    _equal(harbor_lock.get("n_concurrent_trials"), 1, "Harbor concurrency")
    _equal((trial_lock.get("agent") or {}).get("n_concurrent"), 1, "agent concurrency")
    _equal((trial_lock.get("agent") or {}).get("model_name"), f"openai/{MODEL_ID}", "Harbor model")
    _equal(harbor_config.get("n_concurrent_trials"), 1, "resolved concurrency")
    _equal(launch.get("wrapper_retries"), 0, "wrapper retries")
    command = launch.get("command")
    if not isinstance(command, list) or "--upload" in command or "--public" in command:
        raise ValidationError("paid launch command is invalid")
    _equal(implementation_budget.get("status"), "completed", "implementation budget status")
    _equal(implementation_budget.get("implementation_spend_usd"), spent, "implementation budget spend")
    _equal(job_result.get("n_total_trials"), 1, "job trial count")
    _equal(job_result.get("stats", {}).get("n_retries"), 0, "job retries")

    agent_seconds = agent.get("agent_time_seconds")
    if isinstance(agent_seconds, bool) or not isinstance(agent_seconds, int | float) or agent_seconds <= 0:
        raise ValidationError("agent timing is invalid")
    harbor_agent_seconds = _duration_seconds(trial.get("agent_execution"), "agent execution")
    verifier_seconds = _duration_seconds(trial.get("verifier"), "verifier")
    wall_seconds = _duration_seconds(
        {"started_at": trial.get("started_at"), "finished_at": trial.get("finished_at")},
        "wall",
    )
    artifact_prefix = str(artifact_dir.resolve().relative_to(REPOSITORY_ROOT))
    receipt_paths = {Path(name).stem.lower().replace("-", "_"): f"{artifact_prefix}/{name}" for name in required_files}
    receipt_paths["sha256_summary"] = f"{artifact_prefix}/SHA256SUMS.json"
    return {
        "schema_version": 2,
        "passed": True,
        "task": TASK_NAME,
        "reward": reward,
        "requests": len(requests),
        "tokens": totals,
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "tool_counts": dict(sorted(Counter(tool_names).items())),
        "agent_seconds": float(agent_seconds),
        "harbor_agent_phase_seconds": harbor_agent_seconds,
        "verifier_seconds": verifier_seconds,
        "wall_seconds": wall_seconds,
        "actual_cash_cost_usd": actual_cash_cost,
        "api_equivalent_cost_usd": float(spent),
        "cost_basis": {
            "description": agent.get("cost_basis"),
            "ordinary_input_usd_per_million": 5.0,
            "cached_input_usd_per_million": 0.5,
            "output_including_reasoning_usd_per_million": 30.0,
            "cache_write_tokens_recorded_separately_and_excluded_by_frozen_calculator": True,
        },
        "identity": {
            "reproduction_repository_commit": _PAID_RUN_REPOSITORY_COMMIT,
            "thinharness_commit": THINHARNESS_COMMIT,
            "thinharness_version": agent.get("thinharness", {}).get("version"),
            "wheel_sha256": wheel_sha256,
            "prompt_sha256": PROMPT_SHA256,
            "dataset_digest": DATASET_DIGEST,
            "model": MODEL_ID,
            "response_models": agent.get("response_models"),
            "harbor_version": harbor_lock.get("harbor", {}).get("version"),
            "environment": agent.get("execution"),
            "staged_control_sha256": agent.get("staged_control_sha256"),
        },
        "receipts": receipt_paths,
    }


def _duration_seconds(value: Any, label: str) -> float:
    if not isinstance(value, dict) or not isinstance(value.get("started_at"), str) or not isinstance(value.get("finished_at"), str):
        raise ValidationError(f"{label} timestamps are missing")
    started = datetime.fromisoformat(value["started_at"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(value["finished_at"].replace("Z", "+00:00"))
    duration = (finished - started).total_seconds()
    if duration <= 0:
        raise ValidationError(f"{label} duration is invalid")
    return duration


def _equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValidationError(f"{label} differs: expected {expected!r}, got {actual!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("receipt", type=Path)
    paid = sub.add_parser("paid")
    paid.add_argument("job_dir", type=Path)
    paid.add_argument("--report", type=Path)
    paid_artifacts = sub.add_parser("paid-artifacts")
    paid_artifacts.add_argument("artifact_dir", type=Path)
    paid_artifacts.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "preflight":
        result = validate_container_preflight(args.receipt)
    elif args.mode == "paid":
        result = validate_paid_job(args.job_dir)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        result = validate_paid_artifacts(args.artifact_dir)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
