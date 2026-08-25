"""Validation and trace comparison for the matched subscription smoke."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .budget import (
    CACHE_WRITE_USD_PER_TOKEN,
    CACHED_INPUT_USD_PER_TOKEN,
    ORDINARY_INPUT_USD_PER_TOKEN,
    OUTPUT_USD_PER_TOKEN,
    api_equivalent_cost_usd,
)
from .subscription_constants import (
    CPROXY_COMMIT,
    CPROXY_UPSTREAM,
    CPROXY_VERSION,
    DATASET_DIGEST,
    EXPECTED_CELLS,
    MODEL,
    NODE_VERSION,
    PI_VERSION,
    PROMPT_SHA256,
    REASONING,
    REPOSITORY_ROOT,
    TASKS,
    TEXT,
    THINHARNESS_COMMIT,
)


class SubscriptionValidationError(RuntimeError):
    """Durable subscription evidence does not prove the frozen comparison."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SubscriptionValidationError(f"JSON is not an object: {path}")
    return value


def _equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise SubscriptionValidationError(f"{label} differs: expected {expected!r}, got {actual!r}")


def _trial_dir(cell: Path) -> Path:
    job = cell / "job"
    trials = [path for path in job.iterdir() if path.is_dir()]
    if len(trials) != 1:
        raise SubscriptionValidationError(f"expected one trial under {job}")
    return trials[0]


def _audit(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise SubscriptionValidationError("gateway audit line is not an object")
        records.append(value)
    if not records:
        raise SubscriptionValidationError("gateway audit is empty")
    return records


def _seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()


def _validate_selection(selection: dict[str, Any]) -> None:
    _equal(selection.get("dataset", {}).get("digest"), DATASET_DIGEST, "selection dataset")
    selected = [item.get("task") for item in selection.get("selected", [])]
    _equal(set(selected), set(TASKS), "selected task set")
    excluded = set(selection.get("excluded_prior_paid_or_launched_tasks", []))
    if excluded & set(TASKS):
        raise SubscriptionValidationError("selected task appears in prior paid exclusions")
    if len(selected) != 3 or len(set(selected)) != 3:
        raise SubscriptionValidationError("selection must contain exactly three tasks")
    _equal(selection.get("planned_execution_order"), list(EXPECTED_CELLS), "planned cell order")
    for item in selection["selected"]:
        if item.get("expert_time_estimate_min") != 15.0:
            raise SubscriptionValidationError("selected task is not in the minimum remaining expert-time tier")
        if item.get("memory_mb", 10**9) > 4096 or item.get("agent_timeout_sec", 10**9) > 1800:
            raise SubscriptionValidationError("selected task exceeds smoke resource bounds")
        for key in ("task_toml_sha256", "amd64_image_digest"):
            value = item.get(key)
            if not isinstance(value, str) or not value.startswith("sha256:") and len(value) != 64:
                raise SubscriptionValidationError(f"selection {key} is invalid")


def _validate_cell(cell: Path, *, expected_mode: str, expected_cell_id: str) -> dict[str, Any]:
    trial = _trial_dir(cell)
    result = _read(trial / "result.json")
    lock = _read(trial / "lock.json")
    job_lock = _read(cell / "job" / "lock.json")
    gateway_identity = _read(cell / "gateway-identity.json")
    launch = _read(cell / "launch.json")
    harness = expected_cell_id.rsplit("--", 1)[1]
    task = expected_cell_id.rsplit("--", 1)[0]
    receipt_name = f"{harness}-subscription-result.json"
    receipt = _read(trial / "agent" / receipt_name)
    audits = _audit(cell / "gateway-audit.jsonl")

    _equal(receipt.get("cell_id"), expected_cell_id, "receipt cell")
    _equal(receipt.get("harness"), harness, "receipt harness")
    _equal(receipt.get("mode"), expected_mode, "receipt mode")
    _equal(receipt.get("execution", {}).get("execution"), "harbor-task-container", "execution")
    _equal(receipt.get("execution", {}).get("cwd"), "/app", "container cwd")
    _equal(receipt.get("execution", {}).get("root"), "/app", "container root")
    _equal(receipt.get("model"), MODEL, "model")
    _equal(receipt.get("reasoning"), REASONING, "reasoning")
    _equal(receipt.get("text"), TEXT, "text")
    _equal(receipt.get("prompt_sha256"), PROMPT_SHA256, "prompt")
    _equal(receipt.get("direct_openai"), False, "direct API route")
    _equal(receipt.get("codex_oauth_in_container"), False, "container OAuth")
    _equal(receipt.get("error"), None, "agent error")
    _equal(receipt.get("response_models"), [MODEL], "response models")
    _equal(set(receipt.get("tool_names", [])), {"read", "bash", "edit", "write"}, "native tool names")
    _equal(
        set(receipt.get("tool_call_names", [])),
        {"bash"} if expected_mode == "fake" else set(receipt.get("tool_call_names", [])),
        "fake native Bash",
    )
    if expected_mode == "fake":
        _equal(receipt.get("request_count"), 2, "fake request count")
        _equal(receipt.get("tool_count"), 1, "fake tool count")
        if harness == "pi":
            ends = receipt.get("tool_execution_ends") or []
            _equal(len(ends), 1, "Pi fake tool result count")
            _equal(ends[0].get("isError"), False, "Pi fake native Bash result")
            content = json.dumps(ends[0].get("result"), sort_keys=True)
        else:
            records = receipt.get("tool_call_records") or []
            _equal(len(records), 1, "ThinHarness fake tool result count")
            _equal(records[0].get("result", {}).get("ok"), True, "ThinHarness fake native Bash result")
            content = json.dumps(records[0].get("result"), sort_keys=True)
        if "no reusable model credential in task container" not in content:
            raise SubscriptionValidationError("native Bash did not prove reusable credential absence")
    if not receipt.get("verifier_handoff", {}).get("ready"):
        raise SubscriptionValidationError("agent did not reach verifier handoff")
    retries = receipt.get("retries") or {}
    if any(value != 0 for value in retries.values()):
        raise SubscriptionValidationError("agent/provider retries are not zero")

    install = receipt.get("install") or {}
    if harness == "thinharness":
        _equal(install.get("canonical_commit"), THINHARNESS_COMMIT, "ThinHarness commit")
        _equal(install.get("installed_version"), "0.7.0", "ThinHarness version")
        _equal(install.get("source_mode"), "transient-local-git-bundle", "ThinHarness source mode")
        if not isinstance(install.get("wheel_sha256"), str):
            raise SubscriptionValidationError("ThinHarness wheel hash is missing")
        transport = receipt.get("provider_transport") or {}
        _equal(transport.get("provider_timeout_seconds"), 1800, "ThinHarness provider timeout")
        _equal(
            transport.get("client_timeout_seconds"),
            {"connect": 1800, "pool": 1800, "read": 1800, "write": 1800},
            "ThinHarness effective client timeout",
        )
        _equal(transport.get("provider_owns_client"), True, "ThinHarness provider client ownership")
        origins = receipt.get("tool_origins") or {}
        _equal(
            {name: value.get("plugin") for name, value in origins.items()},
            {"bash": "bash", "read": "filesystem", "edit": "filesystem", "write": "filesystem"},
            "ThinHarness plugin origins",
        )
    else:
        _equal(install.get("pi_version"), PI_VERSION, "Pi version")
        _equal(install.get("node_version"), f"v{NODE_VERSION}", "Node version")
        schemas = receipt.get("tools", {}).get("tools")
        if not isinstance(schemas, list) or len(schemas) != 4:
            raise SubscriptionValidationError("Pi native tool schemas are incomplete")

    _equal(gateway_identity.get("mode"), expected_mode, "gateway mode")
    _equal(gateway_identity.get("cproxy", {}).get("version"), CPROXY_VERSION, "cproxy version")
    _equal(gateway_identity.get("cproxy", {}).get("commit"), CPROXY_COMMIT, "cproxy commit")
    _equal(gateway_identity.get("cproxy", {}).get("upstream"), CPROXY_UPSTREAM, "Codex backend route")
    _equal(gateway_identity.get("downstream_token_persisted"), False, "ephemeral token persistence")
    _equal(gateway_identity.get("codex_auth", {}).get("validated"), expected_mode == "real", "Codex auth validation")
    _equal(launch.get("direct_openai"), False, "launch direct API")
    _equal(launch.get("gateway", {}).get("cproxy_commit"), CPROXY_COMMIT, "launch cproxy commit")
    runner_identity = launch.get("runner_identity") or {}
    runner_files = runner_identity.get("files")
    if not isinstance(runner_identity.get("git_head"), str) or not isinstance(runner_files, dict) or not runner_files:
        raise SubscriptionValidationError("runner source identity is incomplete")
    runner_digest = hashlib.sha256(json.dumps(runner_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _equal(runner_identity.get("files_sha256"), runner_digest, "runner source identity")
    if any(value != 0 for value in (launch.get("retries") or {}).values()):
        raise SubscriptionValidationError("launch retries are not zero")

    for sequence, audit in enumerate(audits, 1):
        _equal(audit.get("sequence"), sequence, "gateway sequence")
        _equal(audit.get("response_model"), MODEL, "gateway response identity")
        _equal(audit.get("cproxy", {}).get("upstream"), CPROXY_UPSTREAM, "gateway upstream")
        request = audit.get("request") or {}
        _equal(request.get("model"), MODEL, "wire model")
        _equal(request.get("reasoning"), REASONING, "wire reasoning")
        _equal(request.get("text"), TEXT, "wire text")
        usage = audit.get("usage") or {}
        if not isinstance(usage.get("input_tokens"), int) or not isinstance(usage.get("output_tokens"), int):
            raise SubscriptionValidationError("gateway usage omits token totals")
        if not isinstance((usage.get("input_tokens_details") or {}).get("cached_tokens"), int):
            raise SubscriptionValidationError("gateway usage omits cache reads")
        if not isinstance((usage.get("input_tokens_details") or {}).get("cache_write_tokens"), int):
            raise SubscriptionValidationError("gateway usage omits cache-write tokens")
        if not isinstance((usage.get("output_tokens_details") or {}).get("reasoning_tokens"), int):
            raise SubscriptionValidationError("gateway usage omits reasoning")
        _equal(audit.get("incoming_stream"), harness == "pi", "protocol streaming shape")
    _equal(len(audits), receipt.get("request_count"), "gateway/agent request count")

    _equal(job_lock.get("retry", {}).get("max_retries"), 0, "Harbor retries")
    _equal(job_lock.get("n_concurrent_trials"), 1, "Harbor concurrency")
    _equal((lock.get("agent") or {}).get("n_concurrent"), 1, "agent concurrency")
    _equal((lock.get("task") or {}).get("name"), f"terminal-bench/{task}", "task identity")
    _equal(result.get("exception_info"), None, "trial exception")
    reward = (result.get("verifier_result") or {}).get("rewards", {}).get("reward")
    if expected_mode == "fake":
        _equal(reward, 0.0, "expected unsolved fake reward")
    reward_file = float((trial / "verifier" / "reward.txt").read_text(encoding="utf-8").strip())
    _equal(reward_file, reward, "reward receipt")

    usage = _usage_from_audits(audits)
    tool_names = receipt.get("tool_call_names") or []
    return {
        "cell_id": expected_cell_id,
        "task": task,
        "harness": harness,
        "reward": reward,
        "request_count": len(audits),
        "tool_count": len(tool_names),
        "tool_names": tool_names,
        "usage": usage,
        "agent_seconds": receipt.get("agent_seconds"),
        "wall_seconds": _seconds(result["started_at"], result["finished_at"]),
        "agent_phase_seconds": _seconds(result["agent_execution"]["started_at"], result["agent_execution"]["finished_at"]),
        "verifier_seconds": _seconds(result["verifier"]["started_at"], result["verifier"]["finished_at"]),
        "response_models": receipt.get("response_models"),
        "install": install,
        "gateway": gateway_identity.get("cproxy"),
        "runner_identity": runner_identity,
        "request_payload_bytes": [len(json.dumps(item["request"], separators=(",", ":")).encode()) for item in audits],
        "request_usage": [item.get("usage") for item in audits],
        "request_durations_seconds": [item.get("duration_seconds") for item in audits],
        "batching": _request_batching(audits),
        "tool_arguments": _tool_arguments(receipt),
        "verifier_evidence": _verifier_evidence(trial),
        "artifact": str(cell.resolve().relative_to(REPOSITORY_ROOT)),
    }


def _usage_from_audits(audits: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "input_tokens": 0,
        "ordinary_input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    for item in audits:
        usage = item["usage"]
        details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        input_tokens = usage.get("input_tokens")
        cached = details.get("cached_tokens")
        cache_write = details.get("cache_write_tokens")
        output = usage.get("output_tokens")
        reasoning = output_details.get("reasoning_tokens")
        values = (input_tokens, cached, output, reasoning)
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values):
            raise SubscriptionValidationError("gateway usage has invalid token counts")
        if not isinstance(cache_write, int) or isinstance(cache_write, bool) or cache_write < 0:
            raise SubscriptionValidationError("gateway usage omits exact cache-write tokens")
        ordinary = input_tokens - cached - cache_write
        if ordinary < 0 or reasoning > output:
            raise SubscriptionValidationError("gateway usage token classes do not reconcile")
        totals["input_tokens"] += input_tokens
        totals["cached_input_tokens"] += cached
        totals["cache_write_tokens"] += cache_write
        totals["ordinary_input_tokens"] += ordinary
        totals["output_tokens"] += output
        totals["reasoning_tokens"] += reasoning
    totals["api_equivalent_cost_usd"] = api_equivalent_cost_usd(
        ordinary_input_tokens=totals["ordinary_input_tokens"],
        cached_input_tokens=totals["cached_input_tokens"],
        cache_write_tokens=totals["cache_write_tokens"],
        output_tokens=totals["output_tokens"],
    )
    return totals


def _request_batching(audits: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [
        sum(item.get("type") == "function_call" for item in (audit.get("response", {}).get("output") or []) if isinstance(item, dict))
        for audit in audits
    ]
    return {
        "tool_calls_per_response": calls,
        "tool_bearing_responses": sum(value > 0 for value in calls),
        "multi_tool_responses": sum(value > 1 for value in calls),
        "max_tool_calls_in_response": max(calls, default=0),
    }


def _verifier_evidence(trial: Path) -> dict[str, Any]:
    verifier = trial / "verifier"
    evidence = {}
    for name in ("reward.txt", "ctrf.json", "test-stdout.txt"):
        path = verifier / name
        if not path.is_file():
            raise SubscriptionValidationError(f"verifier evidence is missing: {path}")
        evidence[name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return evidence


def _tool_arguments(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    if receipt.get("harness") == "pi":
        return [{"name": item.get("toolName"), "arguments": item.get("args")} for item in receipt.get("tool_execution_starts", [])]
    result = []
    for item in receipt.get("tool_call_records", []):
        call = item.get("call") or {}
        result.append({"name": call.get("name"), "arguments": call.get("arguments")})
    return result


def validate_cell(root: Path, *, mode: str, cell_id: str) -> dict[str, Any]:
    """Validate one archived cell before the launcher can start the next cell."""
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    if cell_id not in EXPECTED_CELLS:
        raise SubscriptionValidationError(f"unexpected cell id: {cell_id}")
    return _validate_cell(root, expected_mode=mode, expected_cell_id=cell_id)


def validate_artifacts(root: Path, *, mode: str) -> dict[str, Any]:
    """Validate the six fake preflight cells or six real matched cells."""
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    selection = _read(root / "selection.json")
    _validate_selection(selection)
    state = _read(root / "run-state.json")
    _equal(state.get("status"), "completed", "run status")
    _equal(state.get("gateway_mode"), mode, "run gateway mode")
    actual_cells = sorted(path.name for path in (root / "cells").iterdir() if path.is_dir())
    expected = sorted(EXPECTED_CELLS)
    _equal(actual_cells, expected, "artifact cells")
    cells = [_validate_cell(root / "cells" / cell_id, expected_mode=mode, expected_cell_id=cell_id) for cell_id in actual_cells]
    runner_identities = {cell["runner_identity"]["files_sha256"] for cell in cells}
    if len(runner_identities) != 1:
        raise SubscriptionValidationError("cells used different runner source identities")
    _equal(state.get("runner_identity", {}).get("files_sha256"), next(iter(runner_identities)), "state runner identity")
    backend_preflight = None
    if mode == "fake":
        backend_preflight = _read(root / "codex-backend-preflight.json")
        _equal(backend_preflight.get("mode"), "real", "backend preflight mode")
        _equal(backend_preflight.get("codex_auth", {}).get("validated"), True, "Codex OAuth validation")
        _equal(backend_preflight.get("cproxy", {}).get("version"), CPROXY_VERSION, "backend cproxy version")
        _equal(backend_preflight.get("cproxy", {}).get("commit"), CPROXY_COMMIT, "backend cproxy commit")
        _equal(backend_preflight.get("cproxy", {}).get("upstream"), CPROXY_UPSTREAM, "backend upstream")
        _equal(backend_preflight.get("subscription_requests"), 0, "backend preflight subscription requests")
        _equal(backend_preflight.get("upstream_network_requests"), 0, "backend preflight upstream requests")
        if (root / "codex-backend-preflight-audit.jsonl").exists():
            raise SubscriptionValidationError("backend preflight audit proves an unexpected subscription request")
    result: dict[str, Any] = {
        "schema_version": 1,
        "passed": True,
        "mode": mode,
        "backend": "cproxy-codex-subscription" if mode == "real" else "controlled-fake-cproxy-contract",
        "direct_openai": False,
        "selected_tasks": list(TASKS),
        "cells": cells,
        "versions": {"cproxy": CPROXY_VERSION, "cproxy_commit": CPROXY_COMMIT, "pi": PI_VERSION, "thinharness_commit": THINHARNESS_COMMIT},
        "model": MODEL,
        "reasoning": REASONING,
        "text": TEXT,
        "api_equivalent_price_schedule_usd_per_token": {
            "ordinary_input": ORDINARY_INPUT_USD_PER_TOKEN,
            "cached_input": CACHED_INPUT_USD_PER_TOKEN,
            "cache_write": CACHE_WRITE_USD_PER_TOKEN,
            "output": OUTPUT_USD_PER_TOKEN,
        },
        "subscription_cash_cost": None,
        "runner_identity": cells[0]["runner_identity"],
        "codex_backend_preflight": backend_preflight,
        "unavoidable_mismatches": [
            "Pi uses streaming OpenAI Responses and the gateway re-emits cproxy's complete response as SSE; "
            "ThinHarness uses cproxy's non-streaming JSON response.",
            "Pi and ThinHarness use their own native filesystem and Bash schemas and declaration order. Tool names, workspace root, "
            "prompt, model, reasoning, text verbosity, backend, retry policy, and task are matched.",
            "Pi serializes the frozen prompt through its native developer/system input while ThinHarness uses native Responses "
            "instructions; the prompt text and hash are identical.",
            "Pi 0.84.2 native Bash inherits the process environment containing the ephemeral per-cell gateway bearer; ThinHarness filters "
            "that bearer. OAuth never enters either container, the bearer expires when the cell gateway stops, and every use is audited.",
            "The subscription backend reports no cash cost. API-equivalent cost uses the repository's frozen direct-API schedule "
            "and is not cash cost.",
        ],
    }
    if mode == "real":
        result["pairs"] = _compare_pairs(cells)
        result["totals"] = _totals(cells)
        result["aggregate_comparison"] = _aggregate_comparison(result["totals"])
        result["post_fix_four_task_sample"] = _post_fix_four_task_sample(cells)
        result["scope_limit"] = (
            "This descriptive sample contains only the three extension tasks and crack-7z-hash. "
            "Do not generalize beyond these four post-fix tasks."
        )
    return result


def _compare_pairs(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(cell["task"], cell["harness"]): cell for cell in cells}
    pairs = []
    for task in TASKS:
        pi = by_key[(task, "pi")]
        thin = by_key[(task, "thinharness")]
        observations = []
        if pi["request_count"] != thin["request_count"]:
            observations.append(
                {
                    "fact": "request_count_differs",
                    "pi": pi["request_count"],
                    "thinharness": thin["request_count"],
                    "trace_evidence": "gateway-audit.jsonl line counts",
                }
            )
        if pi["tool_names"] != thin["tool_names"]:
            observations.append(
                {
                    "fact": "tool_trajectory_differs",
                    "pi": pi["tool_names"],
                    "thinharness": thin["tool_names"],
                    "trace_evidence": "native tool execution records",
                }
            )
        if pi["request_payload_bytes"] != thin["request_payload_bytes"]:
            observations.append(
                {
                    "fact": "serialized_request_sizes_differ",
                    "pi": pi["request_payload_bytes"],
                    "thinharness": thin["request_payload_bytes"],
                    "trace_evidence": "sanitized gateway request bodies",
                }
            )
        if pi["usage"] != thin["usage"]:
            observations.append(
                {
                    "fact": "backend_usage_differs",
                    "pi": pi["usage"],
                    "thinharness": thin["usage"],
                    "trace_evidence": "Codex response.completed usage fields",
                }
            )
        pairs.append(
            {
                "task": task,
                "pi": pi,
                "thinharness": thin,
                "differences": {
                    "reward": pi["reward"] - thin["reward"],
                    "requests": pi["request_count"] - thin["request_count"],
                    "tools": pi["tool_count"] - thin["tool_count"],
                    "wall_seconds": pi["wall_seconds"] - thin["wall_seconds"],
                },
                "trace_observations": observations
                or [{"fact": "no_recorded_trajectory_or_usage_difference", "trace_evidence": "gateway and native tool traces"}],
            }
        )
    return pairs


def _totals(cells: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    for harness in ("pi", "thinharness"):
        subset = [cell for cell in cells if cell["harness"] == harness]
        usage_keys = (
            "input_tokens",
            "ordinary_input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
            "api_equivalent_cost_usd",
        )
        totals[harness] = {
            "reward": sum(cell["reward"] for cell in subset),
            "passes": sum(cell["reward"] == 1.0 for cell in subset),
            "requests": sum(cell["request_count"] for cell in subset),
            "tools": sum(cell["tool_count"] for cell in subset),
            "wall_seconds": sum(cell["wall_seconds"] for cell in subset),
            "agent_seconds": sum(cell["agent_seconds"] for cell in subset),
            "agent_phase_seconds": sum(cell["agent_phase_seconds"] for cell in subset),
            "verifier_seconds": sum(cell["verifier_seconds"] for cell in subset),
            **{key: sum(cell["usage"][key] for cell in subset) for key in usage_keys},
        }
    return totals


def _aggregate_comparison(totals: dict[str, Any]) -> dict[str, Any]:
    pi = totals["pi"]
    thin = totals["thinharness"]
    comparable = (
        "reward",
        "passes",
        "requests",
        "tools",
        "wall_seconds",
        "agent_seconds",
        "agent_phase_seconds",
        "verifier_seconds",
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
        "api_equivalent_cost_usd",
    )
    return {"pi_minus_thinharness": {key: pi[key] - thin[key] for key in comparable}}


def _post_fix_four_task_sample(extension_cells: list[dict[str, Any]]) -> dict[str, Any]:
    crack_root = REPOSITORY_ROOT / "artifacts" / "codex-subscription-crack-7z-recovery"
    validate_hashes(crack_root)
    crack = _read(crack_root / "SUMMARY.json")
    _equal(crack.get("passed"), True, "preserved crack-7z result")
    _equal(crack.get("selected_tasks"), ["crack-7z-hash"], "preserved crack-7z task")
    crack_cells = crack.get("cells")
    if not isinstance(crack_cells, list) or len(crack_cells) != 2:
        raise SubscriptionValidationError("preserved crack-7z cells are incomplete")
    normalized = []
    for cell in crack_cells:
        copied = dict(cell)
        usage = dict(copied.get("usage") or {})
        required = ("ordinary_input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens")
        if not all(isinstance(usage.get(key), int) for key in required):
            raise SubscriptionValidationError("preserved crack-7z usage is incomplete")
        usage["api_equivalent_cost_usd"] = api_equivalent_cost_usd(
            ordinary_input_tokens=usage["ordinary_input_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            cache_write_tokens=usage["cache_write_tokens"],
            output_tokens=usage["output_tokens"],
        )
        copied["usage"] = usage
        normalized.append(copied)
    all_cells = [*normalized, *extension_cells]
    return {
        "tasks": ["crack-7z-hash", *TASKS],
        "task_count": 4,
        "cells": 8,
        "source": "artifacts/codex-subscription-crack-7z-recovery/SUMMARY.json plus this extension",
        "totals": (totals := _totals(all_cells)),
        "aggregate_comparison": _aggregate_comparison(totals),
        "scope_limit": "Descriptive only; do not generalize beyond these four post-fix tasks.",
    }


def write_hashes(root: Path) -> dict[str, Any]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"SHA256SUMS.json", "SUMMARY.json"}:
            files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    value = {"schema_version": 1, "algorithm": "sha256", "files": files}
    (root / "SHA256SUMS.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def validate_hashes(root: Path) -> None:
    value = _read(root / "SHA256SUMS.json")
    files = value.get("files")
    if not isinstance(files, dict):
        raise SubscriptionValidationError("hash manifest files are invalid")
    expected = {
        str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() and path.name not in {"SHA256SUMS.json", "SUMMARY.json"}
    }
    _equal(set(files), expected, "hash manifest file set")
    for name, digest in files.items():
        _equal(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest, f"hash {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "run", "finalize-preflight", "finalize-run"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    mode = "fake" if "preflight" in args.mode else "real"
    result = validate_artifacts(args.root, mode=mode)
    if args.mode.startswith("finalize"):
        (args.root / "SUMMARY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        write_hashes(args.root)
    elif (args.root / "SHA256SUMS.json").exists():
        validate_hashes(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
