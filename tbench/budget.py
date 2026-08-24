"""Fail-closed request accounting for direct OpenAI implementation runs."""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ORDINARY_INPUT_USD_PER_TOKEN = 5.00 / 1_000_000
CACHED_INPUT_USD_PER_TOKEN = 0.50 / 1_000_000
CACHE_WRITE_USD_PER_TOKEN = 6.25 / 1_000_000
OUTPUT_USD_PER_TOKEN = 30.00 / 1_000_000
INPUT_RESERVE_TOKENS = 10_000
MAX_REQUESTED_OUTPUT_TOKENS = 100_000
LEDGER_VERSION = 1


class BudgetError(RuntimeError):
    """The durable ledger cannot safely authorize or settle a request."""


@dataclass(frozen=True)
class Reservation:
    """One authorization persisted before network access."""

    request_id: str
    max_output_tokens: int
    reserved_usd: float


def initialize_ledger(
    path: Path,
    *,
    launch_id: str,
    dataset_digest: str,
    task: str,
    model: str,
    attempt_ceiling_usd: float,
    implementation_ceiling_usd: float,
    prior_implementation_spend_usd: float,
) -> dict[str, Any]:
    """Create a new attempt ledger without replacing prior evidence."""
    if path.exists():
        raise BudgetError(f"refusing to replace budget ledger: {path}")
    for value, name in (
        (attempt_ceiling_usd, "attempt_ceiling_usd"),
        (implementation_ceiling_usd, "implementation_ceiling_usd"),
    ):
        _positive_finite(value, name)
    if not math.isfinite(prior_implementation_spend_usd) or prior_implementation_spend_usd < 0:
        raise BudgetError("prior implementation spend must be finite and non-negative")
    if attempt_ceiling_usd > implementation_ceiling_usd:
        raise BudgetError("attempt ceiling exceeds implementation ceiling")
    if prior_implementation_spend_usd >= implementation_ceiling_usd:
        raise BudgetError("implementation budget is exhausted")
    if not dataset_digest.startswith("sha256:"):
        raise BudgetError("dataset digest is not pinned by sha256")
    ledger: dict[str, Any] = {
        "version": LEDGER_VERSION,
        "launch_id": launch_id,
        "dataset_digest": dataset_digest,
        "task": task,
        "model": model,
        "attempt_ceiling_usd": attempt_ceiling_usd,
        "implementation_ceiling_usd": implementation_ceiling_usd,
        "prior_implementation_spend_usd": prior_implementation_spend_usd,
        "spent_usd": 0.0,
        "reserved_usd": 0.0,
        "in_flight_request_id": None,
        "fatal_error": None,
        "status": "running",
        "requests": [],
    }
    _write(path, ledger)
    return ledger


def load_ledger(path: Path) -> dict[str, Any]:
    """Load and reconcile every accounting total."""
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BudgetError(f"budget ledger does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BudgetError("budget ledger is invalid JSON") from exc
    if not isinstance(ledger, dict) or ledger.get("version") != LEDGER_VERSION:
        raise BudgetError("budget ledger version is invalid")
    for key in ("attempt_ceiling_usd", "implementation_ceiling_usd"):
        _positive_finite(ledger.get(key), key)
    for key in ("prior_implementation_spend_usd", "spent_usd", "reserved_usd"):
        value = ledger.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
            raise BudgetError(f"budget ledger has invalid {key}")
    requests = ledger.get("requests")
    if not isinstance(requests, list):
        raise BudgetError("budget ledger requests are invalid")
    completed = 0.0
    reserved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for request in requests:
        if not isinstance(request, dict) or not isinstance(request.get("request_id"), str):
            raise BudgetError("budget ledger request receipt is invalid")
        request_id = request["request_id"]
        if request_id in seen:
            raise BudgetError("budget ledger has duplicate request ids")
        seen.add(request_id)
        if request.get("status") == "completed":
            cost = request.get("api_equivalent_cost_usd")
            if isinstance(cost, bool) or not isinstance(cost, int | float) or not math.isfinite(cost) or cost < 0:
                raise BudgetError("completed request cost is invalid")
            completed += float(cost)
        elif request.get("status") == "reserved":
            reserved.append(request)
        else:
            raise BudgetError("request status is invalid")
    if abs(completed - float(ledger["spent_usd"])) > 1e-9:
        raise BudgetError("spent total does not match completed receipts")
    in_flight = ledger.get("in_flight_request_id")
    if in_flight is None:
        if reserved or ledger["reserved_usd"] != 0:
            raise BudgetError("budget ledger has an orphaned reservation")
    elif (
        len(reserved) != 1
        or reserved[0]["request_id"] != in_flight
        or abs(float(reserved[0].get("reserved_usd", -1)) - float(ledger["reserved_usd"])) > 1e-9
    ):
        raise BudgetError("in-flight reservation does not reconcile")
    if ledger.get("fatal_error") is not None:
        raise BudgetError(f"budget ledger is stopped: {ledger['fatal_error']}")
    if ledger.get("status") not in {"running", "completed", "failed"}:
        raise BudgetError("budget ledger status is invalid")
    _check_caps(ledger)
    return ledger


def reserve_request(
    path: Path,
    *,
    payload_bytes: int,
    payload_sha256: str,
    prior_input_tokens: int = 0,
    prior_output_tokens: int = 0,
) -> Reservation:
    """Persist a conservative authorization before one HTTP request."""
    ledger = load_ledger(path)
    if ledger["status"] != "running":
        raise BudgetError("attempt is not open")
    if ledger["in_flight_request_id"] is not None:
        raise BudgetError("another request is already in flight")
    if not isinstance(payload_bytes, int) or isinstance(payload_bytes, bool) or payload_bytes < 1:
        raise BudgetError("payload size must be positive")
    if len(payload_sha256) != 64:
        raise BudgetError("payload sha256 is invalid")
    if not isinstance(prior_input_tokens, int) or isinstance(prior_input_tokens, bool) or prior_input_tokens < 0:
        raise BudgetError("prior input token count is invalid")
    if not isinstance(prior_output_tokens, int) or isinstance(prior_output_tokens, bool) or prior_output_tokens < 0:
        raise BudgetError("prior output token count is invalid")
    request_number = len(ledger["requests"]) + 1
    attempt_available = ledger["attempt_ceiling_usd"] - ledger["spent_usd"]
    total_so_far = ledger["prior_implementation_spend_usd"] + ledger["spent_usd"]
    implementation_available = ledger["implementation_ceiling_usd"] - total_so_far
    available = min(attempt_available, implementation_available)
    # UTF-8 bytes upper-bound new BPE tokens. Prior input and output cover the
    # server-side chain referenced by previous_response_id.
    input_reserve_tokens = prior_input_tokens + prior_output_tokens + payload_bytes + INPUT_RESERVE_TOKENS
    input_reserve_usd = input_reserve_tokens * CACHE_WRITE_USD_PER_TOKEN
    affordable_output = math.floor((available - input_reserve_usd) / OUTPUT_USD_PER_TOKEN)
    max_output_tokens = min(MAX_REQUESTED_OUTPUT_TOKENS, affordable_output)
    if max_output_tokens < 1:
        raise BudgetError("budget cannot authorize another request")
    reserved_usd = input_reserve_usd + max_output_tokens * OUTPUT_USD_PER_TOKEN
    request_id = f"{ledger['launch_id']}:{request_number}"
    request = {
        "request_id": request_id,
        "status": "reserved",
        "payload_bytes": payload_bytes,
        "payload_sha256": payload_sha256,
        "prior_input_tokens": prior_input_tokens,
        "prior_output_tokens": prior_output_tokens,
        "input_reserve_tokens": input_reserve_tokens,
        "requested_max_output_tokens": MAX_REQUESTED_OUTPUT_TOKENS,
        "authorized_max_output_tokens": max_output_tokens,
        "reserved_usd": reserved_usd,
    }
    ledger["requests"].append(request)
    ledger["in_flight_request_id"] = request_id
    ledger["reserved_usd"] = reserved_usd
    _write(path, ledger)
    return Reservation(request_id, max_output_tokens, reserved_usd)


def settle_request(
    path: Path,
    *,
    request_id: str,
    response_model: str,
    input_tokens: int,
    ordinary_input_tokens: int,
    cached_input_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    reported_cost_usd: float | None,
) -> float:
    """Settle complete provider usage and stop permanently on a cap breach."""
    ledger = load_ledger(path)
    if ledger["in_flight_request_id"] != request_id:
        raise BudgetError("response does not match the in-flight request")
    counts = {
        "input_tokens": input_tokens,
        "ordinary_input_tokens": ordinary_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts.values()):
        raise BudgetError("response usage is missing or invalid")
    if input_tokens != ordinary_input_tokens + cached_input_tokens + cache_write_tokens:
        raise BudgetError("input token classes do not reconcile")
    if reasoning_tokens > output_tokens:
        raise BudgetError("reasoning tokens exceed output tokens")
    if response_model != ledger["model"]:
        raise BudgetError("response model identity differs from the request")
    if reported_cost_usd is not None and (
        isinstance(reported_cost_usd, bool)
        or not isinstance(reported_cost_usd, int | float)
        or not math.isfinite(reported_cost_usd)
        or reported_cost_usd < 0
    ):
        raise BudgetError("reported cash cost is invalid")
    request = next((r for r in ledger["requests"] if r["request_id"] == request_id), None)
    if request is None or request.get("status") != "reserved":
        raise BudgetError("reservation receipt is missing")
    cost = api_equivalent_cost_usd(
        ordinary_input_tokens=ordinary_input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens,
    )
    request.update(
        {
            "status": "completed",
            "response_model": response_model,
            "usage": counts,
            "reported_cash_cost_usd": reported_cost_usd,
            "api_equivalent_cost_usd": cost,
        }
    )
    ledger["spent_usd"] += cost
    ledger["reserved_usd"] = 0.0
    ledger["in_flight_request_id"] = None
    breach = None
    if cost > request["reserved_usd"] + 1e-9:
        breach = "actual request cost exceeded its reservation"
    elif ledger["spent_usd"] > ledger["attempt_ceiling_usd"] + 1e-9:
        breach = "attempt spend exceeded its ceiling"
    elif ledger["prior_implementation_spend_usd"] + ledger["spent_usd"] > ledger["implementation_ceiling_usd"] + 1e-9:
        breach = "implementation spend exceeded its ceiling"
    if breach:
        ledger["fatal_error"] = breach
        ledger["status"] = "failed"
    _write(path, ledger)
    if breach:
        raise BudgetError(breach)
    return cost


def finalize_ledger(path: Path, *, success: bool) -> dict[str, Any]:
    """Close an attempt only when no request is unresolved."""
    ledger = load_ledger(path)
    if ledger["in_flight_request_id"] is not None:
        raise BudgetError("cannot finalize with an in-flight request")
    ledger["status"] = "completed" if success else "failed"
    _write(path, ledger)
    return ledger


def api_equivalent_cost_usd(
    *,
    ordinary_input_tokens: int,
    cached_input_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate the preserved GPT-5.6 Sol direct-API equivalent price."""
    values = (ordinary_input_tokens, cached_input_tokens, cache_write_tokens, output_tokens)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        raise BudgetError("token counts must be non-negative integers")
    return (
        ordinary_input_tokens * ORDINARY_INPUT_USD_PER_TOKEN
        + cached_input_tokens * CACHED_INPUT_USD_PER_TOKEN
        + cache_write_tokens * CACHE_WRITE_USD_PER_TOKEN
        + output_tokens * OUTPUT_USD_PER_TOKEN
    )


def _check_caps(ledger: dict[str, Any]) -> None:
    if ledger["spent_usd"] + ledger["reserved_usd"] > ledger["attempt_ceiling_usd"] + 1e-9:
        raise BudgetError("attempt accounting exceeds its ceiling")
    total = ledger["prior_implementation_spend_usd"] + ledger["spent_usd"] + ledger["reserved_usd"]
    if total > ledger["implementation_ceiling_usd"] + 1e-9:
        raise BudgetError("implementation accounting exceeds its ceiling")


def _positive_finite(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise BudgetError(f"{name} must be positive and finite")


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
