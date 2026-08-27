"""One-shot control-state recovery for the additional ten-task campaign."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import direct_additional_validate, direct_validate
from .constants import REPOSITORY_ROOT
from .direct_additional_constants import (
    ARTIFACT_DIR,
    BENCHMARK_ID,
    EXPECTED_CELLS,
    MODEL,
    PER_CELL_CAP_USD,
    PREFLIGHT_DIR,
    SELECTION_PATH,
    TOTAL_CAP_USD,
)
from .durable import atomic_json

POLICY_CELL = "model-extraction-relu-logits--thinharness"
POLICY_INDEX = EXPECTED_CELLS.index(POLICY_CELL)
POLICY_RESPONSE = {
    "error": {
        "code": "cyber_policy",
        "message": (
            "This content was flagged for possible cybersecurity risk. If this seems wrong, try rephrasing your request. "
            "To get authorized for security work, join the Trusted Access for Cyber program: https://chatgpt.com/cyber"
        ),
        "param": None,
        "type": "invalid_request",
    }
}
FROZEN_RUNNER_FILES_SHA256 = "075f08bfd9e675341a84144834364578a6eea63682502dd42516e581e5db87ba"
EXPECTED_SETTLED_SPEND = Decimal("11.89850475")
EXPECTED_POLICY_SPEND = Decimal("0.37595325")
EXPECTED_REWARD_COUNT = 13
RECEIPT_NAME = "RECOVERY.json"
_STATE_NAMES = ("budget-ledger.json", "progress.json", "OUTCOME.json")
_ORIGINAL_VALIDATE_CELL = direct_validate.validate_cell


class RecoveryRefused(RuntimeError):
    """The paid evidence does not authorize this narrow recovery."""


def _read_json(path: Path, *, decimals: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal if decimals else float)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryRefused(f"invalid recovery input: {path}") from exc
    if not isinstance(value, dict):
        raise RecoveryRefused(f"recovery input is not an object: {path}")
    return value


def _read_jsonl(path: Path, *, decimals: bool = False) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line, parse_float=Decimal if decimals else float)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryRefused(f"invalid recovery trace: {path}") from exc
    if not values or not all(isinstance(value, dict) for value in values):
        raise RecoveryRefused(f"recovery trace is empty or malformed: {path}")
    return values


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RecoveryRefused(f"recovery input is absent: {path}") from exc


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _trial(cell_dir: Path) -> Path:
    job = cell_dir / "job"
    try:
        trials = [path for path in job.iterdir() if path.is_dir()]
    except OSError as exc:
        raise RecoveryRefused(f"policy cell job is absent: {job}") from exc
    if len(trials) != 1:
        raise RecoveryRefused("policy cell must contain exactly one trial")
    return trials[0]


def _request_cost(audit: list[dict[str, Any]]) -> Decimal:
    total = Decimal(0)
    for item in audit:
        if item.get("status") != 200:
            continue
        cost = item.get("cost_usd")
        usage = item.get("usage")
        if not isinstance(cost, dict) or not isinstance(usage, dict):
            raise RecoveryRefused("successful request has missing usage or billing evidence")
        for name in (
            "input_tokens",
            "ordinary_input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
        ):
            value = usage.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise RecoveryRefused(f"successful request has missing usage: {name}")
        value = cost.get("api_equivalent_total")
        components = cost.get("components")
        if not isinstance(value, (int, Decimal)) or not isinstance(components, dict):
            raise RecoveryRefused("successful request has missing billing evidence")
        expected_components = {
            "ordinary_input": Decimal(usage["ordinary_input_tokens"]) * Decimal("5.0") / Decimal(1_000_000),
            "cached_input": Decimal(usage["cached_input_tokens"]) * Decimal("0.5") / Decimal(1_000_000),
            "cache_write": Decimal(usage["cache_write_tokens"]) * Decimal("6.25") / Decimal(1_000_000),
            "output": Decimal(usage["output_tokens"]) * Decimal("30.0") / Decimal(1_000_000),
        }
        expected = sum(expected_components.values(), Decimal(0))
        for name, expected_component in expected_components.items():
            component = components.get(name)
            if not isinstance(component, (int, Decimal)) or component < 0:
                raise RecoveryRefused(f"successful request has missing billing component: {name}")
            if abs(Decimal(component) - expected_component) > Decimal("1e-12"):
                raise RecoveryRefused(f"successful request billing component differs: {name}")
        if abs(Decimal(value) - expected) > Decimal("1e-12"):
            raise RecoveryRefused("successful request billing total does not reconcile")
        total += expected
    return total


def _validate_runner_identity(progress: dict[str, Any]) -> dict[str, str]:
    identity = progress.get("runner_identity") or {}
    files = identity.get("files")
    if not isinstance(files, dict) or identity.get("files_sha256") != FROZEN_RUNNER_FILES_SHA256:
        raise RecoveryRefused("frozen runner identity hash differs")
    actual: dict[str, str] = {}
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RecoveryRefused("frozen runner identity file map is malformed")
        actual[relative] = _sha256(REPOSITORY_ROOT / relative)
        if actual[relative] != expected:
            raise RecoveryRefused(f"frozen runner identity file differs: {relative}")
    if _canonical_hash(actual) != FROZEN_RUNNER_FILES_SHA256:
        raise RecoveryRefused("frozen runner identity aggregate does not reproduce")
    return actual


def _validate_completed_prefix(root: Path, progress: dict[str, Any], ledger: dict[str, Any]) -> Decimal:
    cells = progress.get("cells")
    if not isinstance(cells, list) or len(cells) != POLICY_INDEX + 1:
        raise RecoveryRefused("progress must contain exactly the 16 consumed cells")
    if [item.get("cell_id") for item in cells] != list(EXPECTED_CELLS[: POLICY_INDEX + 1]):
        raise RecoveryRefused("consumed progress rows differ from the frozen order")
    rewards = 0
    settled = Decimal(0)
    ledger_cells = ledger.get("cells")
    if not isinstance(ledger_cells, dict):
        raise RecoveryRefused("budget ledger cells are malformed")
    for index, cell_id in enumerate(EXPECTED_CELLS[:POLICY_INDEX]):
        cell_dir = root / "cells" / cell_id
        try:
            reproduced = _ORIGINAL_VALIDATE_CELL(
                cell_dir,
                mode="real",
                cell_id=cell_id,
                expected_cells=EXPECTED_CELLS,
                selection_path=SELECTION_PATH,
                benchmark_id=BENCHMARK_ID,
            )
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            raise RecoveryRefused(f"prior completed cell does not validate: {cell_id}: {exc}") from exc
        recorded = _read_json(cell_dir / "CHECKPOINT.json")
        if recorded != reproduced or cells[index] != reproduced or reproduced.get("status") != "completed":
            raise RecoveryRefused(f"prior completed checkpoint does not reconcile: {cell_id}")
        entry = ledger_cells.get(cell_id)
        audit = _read_jsonl(cell_dir / "gateway-audit.jsonl", decimals=True)
        spent = _request_cost(audit)
        if (
            not isinstance(entry, dict)
            or entry.get("consumed") is not True
            or entry.get("status") != "settled"
            or entry.get("request_count") != len(audit)
            or Decimal(str(entry.get("spent_usd"))) != spent
        ):
            raise RecoveryRefused(f"prior completed ledger entry does not reconcile: {cell_id}")
        settled += spent
        if isinstance(reproduced.get("reward"), (int, float)) and reproduced["reward"] > 0:
            rewards += 1
    if rewards != EXPECTED_REWARD_COUNT:
        raise RecoveryRefused("prior completed reward count does not reconcile")
    return settled


def _validate_policy_cell(root: Path, progress: dict[str, Any], ledger: dict[str, Any]) -> tuple[dict[str, Any], Decimal]:
    cell_dir = root / "cells" / POLICY_CELL
    checkpoint = _read_json(cell_dir / "CHECKPOINT.json")
    if progress["cells"][POLICY_INDEX] != checkpoint:
        raise RecoveryRefused("policy checkpoint and progress row differ")
    launch = _read_json(cell_dir / "launch.json")
    gateway = _read_json(cell_dir / "gateway-identity.json")
    if (
        launch.get("benchmark_id", BENCHMARK_ID) != BENCHMARK_ID
        or launch.get("cell_id") != POLICY_CELL
        or launch.get("task") != "model-extraction-relu-logits"
        or launch.get("harness") != "thinharness"
        or launch.get("mode") != "real"
        or (launch.get("runner_identity") or {}).get("files_sha256") != FROZEN_RUNNER_FILES_SHA256
    ):
        raise RecoveryRefused("policy launch identity differs")
    if (
        gateway.get("benchmark_id") != BENCHMARK_ID
        or gateway.get("cell_id") != POLICY_CELL
        or gateway.get("mode") != "real"
        or gateway.get("provider") != "OpenAI"
        or gateway.get("upstream") != "https://api.openai.com/v1/responses"
        or gateway.get("direct_openai") is not True
        or gateway.get("bridge") is not None
        or gateway.get("request_retries") != 0
        or gateway.get("transport_retries") != 0
    ):
        raise RecoveryRefused("policy gateway identity differs")
    markers = _read_jsonl(cell_dir / "MODEL_REQUEST_STARTED.jsonl")
    audit = _read_jsonl(cell_dir / "gateway-audit.jsonl", decimals=True)
    if len(markers) != len(audit) or len(audit) != 7:
        raise RecoveryRefused("policy request marker and gateway audit counts differ")
    for sequence, (marker, item) in enumerate(zip(markers, audit, strict=True), 1):
        if (
            marker.get("benchmark_id") != BENCHMARK_ID
            or marker.get("cell_id") != POLICY_CELL
            or marker.get("sequence") != sequence
            or not isinstance(marker.get("payload_sha256"), str)
            or len(marker["payload_sha256"]) != 64
            or not isinstance(item.get("request_sha256"), str)
            or len(item["request_sha256"]) != 64
            or marker.get("upstream") != item.get("upstream")
            or marker.get("transport_retries") != 0
            or item.get("benchmark_id") != BENCHMARK_ID
            or item.get("cell_id") != POLICY_CELL
            or item.get("sequence") != sequence
        ):
            raise RecoveryRefused("policy request marker and gateway audit do not reconcile")
    if any(item.get("status") != 200 or item.get("response_model") != MODEL for item in audit[:6]):
        raise RecoveryRefused("policy cell does not contain exactly six successful model responses")
    spent = _request_cost(audit)
    terminal = audit[-1]
    if (
        terminal.get("status") != 400
        or terminal.get("credit_exhausted") is not False
        or terminal.get("response") != POLICY_RESPONSE
        or terminal.get("response_model") is not None
        or terminal.get("usage") is not None
        or terminal.get("cost_usd") is not None
        or terminal.get("response_sha256") != _canonical_hash(POLICY_RESPONSE)
    ):
        raise RecoveryRefused("terminal failure is not the exact non-credit cyber_policy refusal")
    if (cell_dir / "CREDIT_EXHAUSTED.json").exists():
        raise RecoveryRefused("credit exhaustion cannot resume")
    trial = _trial(cell_dir)
    result = _read_json(trial / "result.json")
    receipt = _read_json(trial / "agent" / "thinharness-direct-result.json")
    exception = result.get("exception_info") or {}
    if (
        result.get("verifier") is not None
        or result.get("verifier_result") is not None
        or any((trial / "verifier" / name).exists() for name in ("ctrf.json", "reward.txt", "test-stdout.txt"))
        or "cyber_policy" not in str(exception.get("exception_message"))
        or receipt.get("cell_id") != POLICY_CELL
        or receipt.get("mode") != "real"
        or receipt.get("model") != MODEL
        or receipt.get("request_count") != 6
        or receipt.get("response_models") != [MODEL]
    ):
        raise RecoveryRefused("policy native receipt, Harbor outcome, or absent verifier does not reconcile")
    reproduced = direct_validate.cell_summary(cell_dir, status="model_attempt_failed", real_model_attempted=True)
    failure = reproduced.get("model_attempt_failure") or {}
    if (
        reproduced != checkpoint
        or checkpoint.get("never_rerun") is not True
        or checkpoint.get("request_count") != 7
        or checkpoint.get("successful_request_count") != 6
        or checkpoint.get("reward") is not None
        or checkpoint.get("verifier_outcome") is not None
        or failure.get("response") != POLICY_RESPONSE
        or failure.get("credit_exhausted") is not False
        or abs(Decimal(str((checkpoint.get("cost") or {}).get("api_equivalent_total"))) - spent) > Decimal("1e-12")
        or spent != EXPECTED_POLICY_SPEND
    ):
        raise RecoveryRefused("policy checkpoint does not reproduce from the preserved evidence")
    entry = (ledger.get("cells") or {}).get(POLICY_CELL)
    blocked = ledger.get("blocked") or {}
    if (
        not isinstance(entry, dict)
        or entry.get("consumed") is not True
        or entry.get("status") != "consumed"
        or entry.get("request_count") != 7
        or Decimal(str(entry.get("spent_usd"))) != spent
        or ledger.get("active_cell") != POLICY_CELL
        or blocked.get("cell_id") != POLICY_CELL
        or blocked.get("reason") != "cell ended without complete receipt: model_attempt_failed"
    ):
        raise RecoveryRefused("policy ledger entry does not reconcile")
    return checkpoint, spent


def _validate_no_later_consumed(root: Path, ledger: dict[str, Any]) -> None:
    ledger_cells = ledger.get("cells") or {}
    for cell_id in EXPECTED_CELLS[POLICY_INDEX + 1 :]:
        entry = ledger_cells.get(cell_id)
        marker = root / "cells" / cell_id / "MODEL_REQUEST_STARTED.jsonl"
        if (isinstance(entry, dict) and entry.get("consumed") is True) or (marker.is_file() and marker.stat().st_size):
            raise RecoveryRefused(f"a later cell is already consumed: {cell_id}")
        if entry is not None:
            raise RecoveryRefused(f"a later cell already has budget state: {cell_id}")


def _validate_preflight(progress: dict[str, Any]) -> None:
    try:
        report = direct_additional_validate.validate(PREFLIGHT_DIR, expected_mode="fake")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        raise RecoveryRefused(f"frozen no-model preflight does not validate: {exc}") from exc
    if (report.get("runner_identity") or {}).get("files_sha256") != FROZEN_RUNNER_FILES_SHA256:
        raise RecoveryRefused("preflight runner identity differs")
    if (progress.get("runner_identity") or {}).get("files_sha256") != FROZEN_RUNNER_FILES_SHA256:
        raise RecoveryRefused("paid progress runner identity differs")


def _immutable_hashes(root: Path) -> dict[str, str]:
    paths = [
        root / "progress.jsonl",
        root / "SUMMARY.json",
        root / "SHA256SUMS.json",
        PREFLIGHT_DIR / "SHA256SUMS.json",
    ]
    for cell_id in EXPECTED_CELLS[: POLICY_INDEX + 1]:
        cell = root / "cells" / cell_id
        paths.extend(
            (
                cell / "CHECKPOINT.json",
                cell / "MODEL_REQUEST_STARTED.jsonl",
                cell / "gateway-audit.jsonl",
                cell / "gateway-identity.json",
            )
        )
    trial = _trial(root / "cells" / POLICY_CELL)
    paths.extend((trial / "result.json", trial / "agent" / "thinharness-direct-result.json"))
    return {str(path.relative_to(REPOSITORY_ROOT)): _sha256(path) for path in paths}


def _validate_initial(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    progress = _read_json(root / "progress.json")
    ledger = _read_json(root / "budget-ledger.json")
    outcome = _read_json(root / "OUTCOME.json")
    if (
        progress.get("benchmark_id") != BENCHMARK_ID
        or progress.get("mode") != "real"
        or progress.get("planned_cells") != list(EXPECTED_CELLS)
        or progress.get("status") != "fail_closed"
        or progress.get("stop") != {"cell_id": POLICY_CELL, "reason": "model_attempt_failed"}
    ):
        raise RecoveryRefused("paid progress is not the exact recoverable failed state")
    if (
        ledger.get("benchmark_id") != BENCHMARK_ID
        or ledger.get("per_cell_cap_usd") != str(PER_CELL_CAP_USD)
        or ledger.get("total_cap_usd") != str(TOTAL_CAP_USD)
    ):
        raise RecoveryRefused("budget identity or caps differ")
    if (
        outcome.get("benchmark_id") != BENCHMARK_ID
        or outcome.get("mode") != "real"
        or outcome.get("status") != "fail_closed"
        or outcome.get("checkpointed_cells") != POLICY_INDEX + 1
        or outcome.get("planned_cells") != len(EXPECTED_CELLS)
        or outcome.get("stop") != progress.get("stop")
    ):
        raise RecoveryRefused("outcome state does not reconcile with progress")
    _validate_runner_identity(progress)
    _validate_preflight(progress)
    prior_spend = _validate_completed_prefix(root, progress, ledger)
    _, policy_spend = _validate_policy_cell(root, progress, ledger)
    _validate_no_later_consumed(root, ledger)
    if prior_spend + policy_spend != EXPECTED_SETTLED_SPEND or Decimal(str(ledger.get("total_spent_usd"))) != EXPECTED_SETTLED_SPEND:
        raise RecoveryRefused("total settled spend does not reconcile")
    return progress, ledger, outcome, _immutable_hashes(root)


def _state_hashes(root: Path) -> dict[str, str]:
    return {name: _sha256(root / name) for name in _STATE_NAMES}


def _repaired_states(
    progress: dict[str, Any], ledger: dict[str, Any], outcome: dict[str, Any], *, recovered_at: float
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    repaired_ledger = json.loads(json.dumps(ledger))
    policy_entry = repaired_ledger["cells"][POLICY_CELL]
    policy_entry["status"] = "settled"
    policy_entry["finished_at"] = progress["cells"][POLICY_INDEX]["timing"]["launcher_finished_at"]
    repaired_ledger["active_cell"] = None
    repaired_ledger["blocked"] = None
    repaired_ledger["updated_at"] = recovered_at

    repaired_progress = json.loads(json.dumps(progress))
    repaired_progress["status"] = "recovery_ready"
    repaired_progress.pop("finished_at", None)
    repaired_progress.pop("stop", None)
    repaired_progress["budget"] = repaired_ledger
    repaired_progress["updated_at"] = recovered_at

    repaired_outcome = json.loads(json.dumps(outcome))
    repaired_outcome["status"] = "recovery_ready"
    repaired_outcome["stop"] = None
    return repaired_ledger, repaired_progress, repaired_outcome


def _encoded_hash(value: dict[str, Any]) -> str:
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _recovery_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".recovery.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryRefused("another recovery command holds the lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def recover(root: Path = ARTIFACT_DIR) -> dict[str, Any]:
    """Validate the exact refusal and durably unblock only its control state."""
    root = root.resolve()
    receipt_path = root / RECEIPT_NAME
    with _recovery_lock(root):
        if receipt_path.is_file():
            receipt = _read_json(receipt_path)
            if receipt.get("status") == "completed":
                validate_activation_receipt(root)
                return receipt
            if receipt.get("status") != "prepared":
                raise RecoveryRefused("existing recovery receipt is not resumable")
            before = receipt.get("before_state_sha256") or {}
            after = receipt.get("after_state_sha256") or {}
            current = _state_hashes(root)
            if any(current[name] not in {before.get(name), after.get(name)} for name in _STATE_NAMES):
                raise RecoveryRefused("partially recovered state differs from the durable transaction")
            target = receipt.get("target_state") or {}
            if set(target) != set(_STATE_NAMES):
                raise RecoveryRefused("prepared recovery receipt lacks target state")
            repaired = tuple(target[name] for name in _STATE_NAMES)
        else:
            progress, ledger, outcome, immutable = _validate_initial(root)
            recovered_at = time.time()
            repaired = _repaired_states(progress, ledger, outcome, recovered_at=recovered_at)
            before = _state_hashes(root)
            after = {name: _encoded_hash(value) for name, value in zip(_STATE_NAMES, repaired, strict=True)}
            receipt = {
                "schema_version": 1,
                "benchmark_id": BENCHMARK_ID,
                "status": "prepared",
                "recovered_at": recovered_at,
                "policy_cell": POLICY_CELL,
                "reason": "fully preserved non-credit OpenAI 400 cyber_policy refusal is final and consumed",
                "effect": "clear only the policy-failure control block; preserve the cell forever and continue the final four frozen cells",
                "before_state_sha256": before,
                "after_state_sha256": after,
                "immutable_evidence_sha256": immutable,
                "frozen_runner_files_sha256": FROZEN_RUNNER_FILES_SHA256,
                "remaining_cells": list(EXPECTED_CELLS[POLICY_INDEX + 1 :]),
                "target_state": {name: value for name, value in zip(_STATE_NAMES, repaired, strict=True)},
            }
            atomic_json(receipt_path, receipt)
        for name, value in zip(_STATE_NAMES, repaired, strict=True):
            if _sha256(root / name) != after[name]:
                atomic_json(root / name, value)
        if _state_hashes(root) != after:
            raise RecoveryRefused("repaired state hashes do not match the prepared transaction")
        receipt["status"] = "completed"
        receipt.pop("target_state", None)
        atomic_json(receipt_path, receipt)
        validate_activation_receipt(root)
        return receipt


def validate_activation_receipt(root: Path) -> dict[str, Any]:
    """Validate the receipt and immutable refusal before the launcher accepts it."""
    root = root.resolve()
    receipt = _read_json(root / RECEIPT_NAME)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("benchmark_id") != BENCHMARK_ID
        or receipt.get("status") != "completed"
        or receipt.get("policy_cell") != POLICY_CELL
        or receipt.get("frozen_runner_files_sha256") != FROZEN_RUNNER_FILES_SHA256
        or receipt.get("remaining_cells") != list(EXPECTED_CELLS[POLICY_INDEX + 1 :])
    ):
        raise RecoveryRefused("recovery receipt identity differs")
    immutable = receipt.get("immutable_evidence_sha256")
    if not isinstance(immutable, dict) or not immutable:
        raise RecoveryRefused("recovery receipt has no immutable evidence hashes")
    for relative, expected in immutable.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or _sha256(REPOSITORY_ROOT / relative) != expected:
            raise RecoveryRefused(f"recovered immutable evidence differs: {relative}")
    progress = _read_json(root / "progress.json")
    ledger = _read_json(root / "budget-ledger.json")
    cells = progress.get("cells") or []
    if (
        len(cells) < POLICY_INDEX + 1
        or cells[POLICY_INDEX] != _read_json(root / "cells" / POLICY_CELL / "CHECKPOINT.json")
        or (progress.get("runner_identity") or {}).get("files_sha256") != FROZEN_RUNNER_FILES_SHA256
        or ((ledger.get("cells") or {}).get(POLICY_CELL) or {}).get("status") != "settled"
    ):
        raise RecoveryRefused("recovered policy state is no longer final and consumed")
    _validate_policy_cell_after_recovery(root, progress, ledger)
    return receipt


def _validate_policy_cell_after_recovery(root: Path, progress: dict[str, Any], ledger: dict[str, Any]) -> None:
    entry = (ledger.get("cells") or {}).get(POLICY_CELL) or {}
    if (
        entry.get("consumed") is not True
        or entry.get("request_count") != 7
        or Decimal(str(entry.get("spent_usd"))) != EXPECTED_POLICY_SPEND
    ):
        raise RecoveryRefused("recovered policy ledger no longer reconciles")
    checkpoint = progress["cells"][POLICY_INDEX]
    if (
        checkpoint.get("status") != "model_attempt_failed"
        or checkpoint.get("never_rerun") is not True
        or checkpoint.get("request_count") != 7
        or checkpoint.get("successful_request_count") != 6
        or (checkpoint.get("model_attempt_failure") or {}).get("response") != POLICY_RESPONSE
        or (checkpoint.get("model_attempt_failure") or {}).get("credit_exhausted") is not False
    ):
        raise RecoveryRefused("recovered policy checkpoint no longer reconciles")


def validate_cell_with_recovery(
    cell_dir: Path,
    *,
    mode: str,
    cell_id: str,
    expected_cells: tuple[str, ...] | None = None,
    selection_path: Path | None = None,
    benchmark_id: str | None = None,
) -> dict[str, Any]:
    """Accept only the receipted policy refusal; delegate every other cell."""
    if mode == "real" and cell_id == POLICY_CELL and cell_dir.resolve() == (ARTIFACT_DIR / "cells" / POLICY_CELL).resolve():
        validate_activation_receipt(ARTIFACT_DIR)
        checkpoint = _read_json(cell_dir / "CHECKPOINT.json")
        reproduced = direct_validate.cell_summary(cell_dir, status="model_attempt_failed", real_model_attempted=True)
        if checkpoint != reproduced:
            raise RecoveryRefused("receipted policy checkpoint no longer reproduces")
        return checkpoint
    arguments: dict[str, Any] = {"mode": mode, "cell_id": cell_id}
    if expected_cells is not None:
        arguments["expected_cells"] = expected_cells
    if selection_path is not None:
        arguments["selection_path"] = selection_path
    if benchmark_id is not None:
        arguments["benchmark_id"] = benchmark_id
    return _ORIGINAL_VALIDATE_CELL(cell_dir, **arguments)


def install_validator() -> None:
    """Install the receipt-gated control-plane validator without changing frozen runner files."""
    if direct_validate.validate_cell is not validate_cell_with_recovery:
        direct_validate.validate_cell = validate_cell_with_recovery


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover one exact non-credit provider-policy refusal")
    parser.add_argument("root", nargs="?", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()
    receipt = recover(args.root)
    print(json.dumps({key: receipt[key] for key in ("status", "policy_cell", "remaining_cells", "after_state_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
