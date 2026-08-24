"""Independent receipt checks for no-model and paid Harbor runs."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    args = parser.parse_args()
    if args.mode == "preflight":
        result = validate_container_preflight(args.receipt)
    else:
        result = validate_paid_job(args.job_dir)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
