"""No-model cap-stop finalization for the additional ten-task campaign."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import direct_additional_recovery as recovery
from . import direct_additional_validate, direct_validate
from .constants import REPOSITORY_ROOT
from .direct_additional_constants import (
    ARTIFACT_DIR,
    BENCHMARK_ID,
    EXPECTED_CELLS,
    MODEL,
    PER_CELL_CAP_USD,
    PREFLIGHT_DIR,
    REPORT_PATH,
    SELECTION_PATH,
    TOTAL_CAP_USD,
)
from .direct_constants import PI_SCHEMAS_PATH, PI_VERSION, PRICES, SETTINGS_PATH
from .durable import atomic_json

CAP_CELL = "make-doom-for-mips--pi"
FINAL_CELL = "make-doom-for-mips--thinharness"
CAP_INDEX = EXPECTED_CELLS.index(CAP_CELL)
FINAL_INDEX = EXPECTED_CELLS.index(FINAL_CELL)
CAP_RECEIPT_NAME = "CAP_STOP.json"
HANDOFF_PATH = REPOSITORY_ROOT / "artifacts" / "direct-openai-additional-10-handoff.md"
HISTORICAL_REPORT_PATH = REPOSITORY_ROOT / "reports" / "direct-openai-20task-analysis.json"
RUNNER_LOG_PATH = REPOSITORY_ROOT / "artifacts" / "direct-openai-additional-10-runner.log"
EXPECTED_PRIOR_SPEND = Decimal("13.86658075")
EXPECTED_CAP_SPEND = Decimal("3.02611250")
EXPECTED_TOTAL_SPEND = Decimal("16.89269325")
EXPECTED_OVERSHOOT = Decimal("0.02611250")
EXPECTED_UPSTREAM_REQUESTS = 41
EXPECTED_NATIVE_ATTEMPTS = 42
EXPECTED_LOCAL_DENIALS = 1
EXPECTED_SCORE = Decimal("15")
EXPECTED_VERIFIER_OUTCOMES = 18
RUNNER_IDENTITY_SHA256 = recovery.FROZEN_RUNNER_FILES_SHA256
CAP_REASON = "per-cell USD 3.00 cap reached or crossed"
LOCAL_DENIAL_ERROR = 'OpenAI API error (502): {"type":"BudgetBlocked","message":"per-cell USD 3.00 cap reached or crossed"}'
FINAL_STOP = {
    "cell_id": CAP_CELL,
    "reason": CAP_REASON,
    "status": "cap_exceeded",
    "unrun_cell": FINAL_CELL,
}
_STATE_PATHS = {
    "budget-ledger.json": "budget-ledger.json",
    "progress.json": "progress.json",
    "OUTCOME.json": "OUTCOME.json",
    "cap_checkpoint": f"cells/{CAP_CELL}/CHECKPOINT.json",
}
_MUTABLE_EVIDENCE = {
    "progress.json",
    "budget-ledger.json",
    "OUTCOME.json",
    "SUMMARY.json",
    "SHA256SUMS.json",
    CAP_RECEIPT_NAME,
    ".cap-stop.lock",
    f"cells/{CAP_CELL}/CHECKPOINT.json",
}
_RECOVERY_CONTINUATION_MUTABLE = {
    f"artifacts/{BENCHMARK_ID}/progress.jsonl",
    f"artifacts/{BENCHMARK_ID}/SUMMARY.json",
    f"artifacts/{BENCHMARK_ID}/SHA256SUMS.json",
}


class FinalizationRefused(RuntimeError):
    """The preserved evidence does not authorize cap-stop finalization."""


@dataclass(frozen=True)
class InitialState:
    progress: dict[str, Any]
    ledger: dict[str, Any]
    outcome: dict[str, Any]
    checkpoint: dict[str, Any]
    immutable_evidence: dict[str, str]


def _read_json(path: Path, *, decimals: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal if decimals else float)
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizationRefused(f"invalid finalization input: {path}") from exc
    if not isinstance(value, dict):
        raise FinalizationRefused(f"finalization input is not an object: {path}")
    return value


def _read_jsonl(path: Path, *, decimals: bool = False) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line, parse_float=Decimal if decimals else float)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizationRefused(f"invalid finalization trace: {path}") from exc
    if not values or not all(isinstance(value, dict) for value in values):
        raise FinalizationRefused(f"finalization trace is empty or malformed: {path}")
    return values


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise FinalizationRefused(f"finalization input is absent: {path}") from exc


def _encoded_hash(value: dict[str, Any]) -> str:
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _trial(cell_dir: Path) -> Path:
    try:
        trials = [path for path in (cell_dir / "job").iterdir() if path.is_dir()]
    except OSError as exc:
        raise FinalizationRefused(f"cell job is absent: {cell_dir}") from exc
    if len(trials) != 1:
        raise FinalizationRefused(f"cell must contain exactly one Harbor trial: {cell_dir.name}")
    return trials[0]


def _seconds(start: str, finish: str) -> float:
    return (datetime.fromisoformat(finish.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()


def _request_cost(audit: list[dict[str, Any]]) -> Decimal:
    try:
        return recovery._request_cost(audit)
    except recovery.RecoveryRefused as exc:
        raise FinalizationRefused(str(exc)) from exc


def _validate_runner_identity(progress: dict[str, Any]) -> None:
    identity = progress.get("runner_identity") or {}
    files = identity.get("files")
    if identity.get("files_sha256") != RUNNER_IDENTITY_SHA256 or not isinstance(files, dict):
        raise FinalizationRefused("frozen runner identity hash differs")
    actual: dict[str, str] = {}
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise FinalizationRefused("frozen runner identity file map is malformed")
        actual[relative] = _sha256(REPOSITORY_ROOT / relative)
        if actual[relative] != expected:
            raise FinalizationRefused(f"frozen runner identity file differs: {relative}")
    if _canonical_hash(actual) != RUNNER_IDENTITY_SHA256:
        raise FinalizationRefused("frozen runner identity aggregate does not reproduce")


def _validate_recovery_receipt(root: Path) -> None:
    receipt_path = root / recovery.RECEIPT_NAME
    receipt = _read_json(receipt_path)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("benchmark_id") != BENCHMARK_ID
        or receipt.get("status") != "completed"
        or receipt.get("policy_cell") != recovery.POLICY_CELL
        or receipt.get("frozen_runner_files_sha256") != RUNNER_IDENTITY_SHA256
        or receipt.get("remaining_cells") != list(EXPECTED_CELLS[recovery.POLICY_INDEX + 1 :])
    ):
        raise FinalizationRefused("recovery receipt identity differs")
    immutable = receipt.get("immutable_evidence_sha256")
    if not isinstance(immutable, dict) or not immutable:
        raise FinalizationRefused("recovery receipt has no immutable evidence hashes")
    for relative, expected in immutable.items():
        if relative in _RECOVERY_CONTINUATION_MUTABLE:
            continue
        if not isinstance(relative, str) or not isinstance(expected, str) or _sha256(REPOSITORY_ROOT / relative) != expected:
            raise FinalizationRefused(f"recovery receipt evidence differs: {relative}")
    before = receipt.get("before_state_sha256") or {}
    after = receipt.get("after_state_sha256") or {}
    if set(before) != {"budget-ledger.json", "progress.json", "OUTCOME.json"} or set(after) != set(before):
        raise FinalizationRefused("recovery receipt state hashes are incomplete")


def _validate_zero_retries_and_identity(root: Path, cell_ids: tuple[str, ...]) -> None:
    expected_retries = {"agent": 0, "harbor": 0, "model": 0, "provider": 0, "transport": 0}
    for cell_id in cell_ids:
        cell = root / "cells" / cell_id
        launch = _read_json(cell / "launch.json")
        gateway = _read_json(cell / "gateway-identity.json")
        if (
            launch.get("cell_id") != cell_id
            or launch.get("mode") != "real"
            or launch.get("retries") != expected_retries
            or (launch.get("runner_identity") or {}).get("files_sha256") != RUNNER_IDENTITY_SHA256
            or gateway.get("benchmark_id") != BENCHMARK_ID
            or gateway.get("cell_id") != cell_id
            or gateway.get("mode") != "real"
            or gateway.get("provider") != "OpenAI"
            or gateway.get("upstream") != "https://api.openai.com/v1/responses"
            or gateway.get("direct_openai") is not True
            or gateway.get("bridge") is not None
            or gateway.get("request_retries") != 0
            or gateway.get("transport_retries") != 0
        ):
            raise FinalizationRefused(f"zero-retry launch or direct gateway identity differs: {cell_id}")


def _validate_prior_cells(root: Path, progress: dict[str, Any]) -> None:
    cells = progress.get("cells")
    if not isinstance(cells, list) or len(cells) not in {CAP_INDEX, CAP_INDEX + 1}:
        raise FinalizationRefused("progress does not contain the exact consumed prefix")
    expected_prefix = EXPECTED_CELLS[: len(cells)]
    if [cell.get("cell_id") for cell in cells] != list(expected_prefix):
        raise FinalizationRefused("consumed cells differ from the frozen Pi-then-ThinHarness order")
    _validate_recovery_receipt(root)
    for index, cell_id in enumerate(EXPECTED_CELLS[:CAP_INDEX]):
        cell_dir = root / "cells" / cell_id
        recorded = _read_json(cell_dir / "CHECKPOINT.json")
        if cell_id == recovery.POLICY_CELL:
            reproduced = direct_validate.cell_summary(cell_dir, status="model_attempt_failed", real_model_attempted=True)
            if (
                recorded != reproduced
                or recorded.get("never_rerun") is not True
                or recorded.get("reward") is not None
                or recorded.get("verifier_outcome") is not None
                or (recorded.get("model_attempt_failure") or {}).get("response") != recovery.POLICY_RESPONSE
            ):
                raise FinalizationRefused("receipted policy refusal does not reproduce")
        else:
            try:
                reproduced = direct_validate.validate_cell(
                    cell_dir,
                    mode="real",
                    cell_id=cell_id,
                    expected_cells=EXPECTED_CELLS,
                    selection_path=SELECTION_PATH,
                    benchmark_id=BENCHMARK_ID,
                )
            except (OSError, RuntimeError, json.JSONDecodeError) as exc:
                raise FinalizationRefused(f"prior completed cell does not validate: {cell_id}: {exc}") from exc
            if recorded.get("status") != "completed" or recorded != reproduced:
                raise FinalizationRefused(f"prior completed checkpoint does not reproduce: {cell_id}")
        if cells[index] != recorded:
            raise FinalizationRefused(f"progress and checkpoint differ: {cell_id}")
    rewards = [cell.get("reward") for cell in cells[:CAP_INDEX] if isinstance(cell.get("reward"), int | float)]
    if len(rewards) != 17 or Decimal(str(sum(rewards))) != EXPECTED_SCORE:
        raise FinalizationRefused("17 prior verifier outcomes or score 15 do not reconcile")


def _validate_local_attempts(
    markers: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    receipt: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(markers) != EXPECTED_UPSTREAM_REQUESTS or len(audit) != EXPECTED_UPSTREAM_REQUESTS:
        raise FinalizationRefused("cap cell must contain exactly 41 markers and 41 gateway audits")
    if receipt.get("request_count") != EXPECTED_NATIVE_ATTEMPTS:
        raise FinalizationRefused("cap cell native receipt must contain exactly 42 attempts")
    turn_starts = [event for event in events if event.get("type") == "turn_start"]
    turn_ends = [event for event in events if event.get("type") == "turn_end"]
    denials = [
        event
        for event in turn_ends
        if isinstance(message := event.get("message"), dict)
        and message.get("stopReason") == "error"
        and message.get("errorMessage") == LOCAL_DENIAL_ERROR
    ]
    if len(turn_starts) != EXPECTED_NATIVE_ATTEMPTS or len(turn_ends) != EXPECTED_NATIVE_ATTEMPTS:
        raise FinalizationRefused("cap cell native event trace must contain exactly 42 complete attempts")
    if len(denials) != EXPECTED_LOCAL_DENIALS or denials[0] is not turn_ends[-1]:
        raise FinalizationRefused("cap cell must contain one terminal local cap denial")
    return {
        "native_model_attempt_count": EXPECTED_NATIVE_ATTEMPTS,
        "upstream_request_count": EXPECTED_UPSTREAM_REQUESTS,
        "request_start_marker_count": EXPECTED_UPSTREAM_REQUESTS,
        "locally_denied_attempt_count": EXPECTED_LOCAL_DENIALS,
    }


def _validate_cap_cell(root: Path) -> dict[str, Any]:
    cell_dir = root / "cells" / CAP_CELL
    launch = _read_json(cell_dir / "launch.json")
    gateway = _read_json(cell_dir / "gateway-identity.json")
    markers = _read_jsonl(cell_dir / "MODEL_REQUEST_STARTED.jsonl")
    audit = _read_jsonl(cell_dir / "gateway-audit.jsonl", decimals=True)
    trial = _trial(cell_dir)
    result = _read_json(trial / "result.json")
    receipt = _read_json(trial / "agent" / "pi-direct-result.json")
    events = _read_jsonl(trial / "agent" / "pi-events.jsonl")
    counts = _validate_local_attempts(markers, audit, receipt, events)
    selection = {item["task"]: item for item in _read_json(SELECTION_PATH)["selected"]}
    frozen_pi = _read_json(PI_SCHEMAS_PATH)
    expected_tools = {"root": frozen_pi["root"], "tools": frozen_pi["tools"]}
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    if (
        launch.get("cell_id") != CAP_CELL
        or launch.get("task") != "make-doom-for-mips"
        or launch.get("harness") != "pi"
        or launch.get("mode") != "real"
        or launch.get("harbor_exit_code") != 0
        or (launch.get("runner_identity") or {}).get("files_sha256") != RUNNER_IDENTITY_SHA256
        or gateway.get("benchmark_id") != BENCHMARK_ID
        or gateway.get("cell_id") != CAP_CELL
        or gateway.get("request_retries") != 0
        or gateway.get("transport_retries") != 0
        or result.get("exception_info") is not None
        or (result.get("task_id") or {}).get("name") != "make-doom-for-mips"
        or (result.get("task_id") or {}).get("ref") != selection["make-doom-for-mips"]["task_package_digest"]
        or receipt.get("cell_id") != CAP_CELL
        or receipt.get("mode") != "real"
        or receipt.get("model") != MODEL
        or receipt.get("response_models") != [MODEL]
        or receipt.get("prompt_sha256") != _read_json(SETTINGS_PATH)["prompt"]["sha256"]
        or receipt.get("openai_key_in_container") is not False
        or receipt.get("harness_version") != PI_VERSION
        or receipt.get("tools") != expected_tools
        or reward != 0
    ):
        raise FinalizationRefused("cap cell native, Harbor, task, model, or verifier identity differs")
    for sequence, (marker, item) in enumerate(zip(markers, audit, strict=True), 1):
        if (
            marker.get("benchmark_id") != BENCHMARK_ID
            or marker.get("cell_id") != CAP_CELL
            or marker.get("sequence") != sequence
            or marker.get("transport_retries") != 0
            or marker.get("upstream") != item.get("upstream")
            or item.get("benchmark_id") != BENCHMARK_ID
            or item.get("cell_id") != CAP_CELL
            or item.get("sequence") != sequence
            or item.get("status") != 200
            or item.get("response_model") != MODEL
        ):
            raise FinalizationRefused("cap request markers and successful gateway audits do not reconcile")
    spent = _request_cost(audit)
    if spent != EXPECTED_CAP_SPEND:
        raise FinalizationRefused("cap cell spend does not equal USD 3.02611250")
    verifier_path = trial / "verifier" / "reward.txt"
    if verifier_path.read_text(encoding="utf-8").strip() != "0" or not (trial / "verifier" / "ctrf.json").is_file():
        raise FinalizationRefused("cap cell verifier evidence does not prove reward 0")
    checkpoint = direct_validate.cell_summary(cell_dir, status="cap_exceeded", real_model_attempted=True)
    checkpoint.update(counts)
    checkpoint["request_count_basis"] = "successful upstream gateway audit records"
    checkpoint["status"] = "cap_exceeded"
    checkpoint["restart_action"] = "never rerun; keep the campaign blocked and leave the final ThinHarness cell unrun"
    checkpoint["local_cap_denial"] = {
        "native_attempt": EXPECTED_NATIVE_ATTEMPTS,
        "upstream_started": False,
        "status": 502,
        "error": {"type": "BudgetBlocked", "message": CAP_REASON},
    }
    checkpoint["cap"] = {
        "currency": "USD",
        "per_cell_usd": str(PER_CELL_CAP_USD),
        "spent_usd": str(EXPECTED_CAP_SPEND),
        "overshoot_usd": str(EXPECTED_OVERSHOOT),
    }
    return checkpoint


def _validate_ledger(root: Path, ledger: dict[str, Any], *, finalized: bool) -> None:
    entries = ledger.get("cells")
    blocked = ledger.get("blocked")
    expected_ids = EXPECTED_CELLS[: CAP_INDEX + 1]
    if (
        ledger.get("benchmark_id") != BENCHMARK_ID
        or ledger.get("per_cell_cap_usd") != str(PER_CELL_CAP_USD)
        or ledger.get("total_cap_usd") != str(TOTAL_CAP_USD)
        or ledger.get("active_cell") != CAP_CELL
        or not isinstance(entries, dict)
        or set(entries) != set(expected_ids)
        or not isinstance(blocked, dict)
        or blocked.get("cell_id") != CAP_CELL
        or blocked.get("reason") != CAP_REASON
    ):
        raise FinalizationRefused("durable cap ledger identity or permanent block differs")
    total = Decimal(0)
    for cell_id in expected_ids:
        entry = entries[cell_id]
        audit = _read_jsonl(root / "cells" / cell_id / "gateway-audit.jsonl", decimals=True)
        spent = _request_cost(audit)
        expected_status = "cap_exceeded" if finalized and cell_id == CAP_CELL else "consumed" if cell_id == CAP_CELL else "settled"
        if (
            entry.get("consumed") is not True
            or entry.get("status") != expected_status
            or entry.get("request_count") != len(audit)
            or Decimal(str(entry.get("spent_usd"))) != spent
        ):
            raise FinalizationRefused(f"budget ledger entry does not reconcile: {cell_id}")
        total += spent
    if total != EXPECTED_TOTAL_SPEND or Decimal(str(ledger.get("total_spent_usd"))) != EXPECTED_TOTAL_SPEND:
        raise FinalizationRefused("total ledger spend does not equal USD 16.89269325")
    final_dir = root / "cells" / FINAL_CELL
    if FINAL_CELL in entries or final_dir.exists():
        raise FinalizationRefused("final ThinHarness cell has model or budget state")


def _immutable_hashes(root: Path) -> dict[str, str]:
    paths = [path for path in root.rglob("*") if path.is_file() and str(path.relative_to(root)) not in _MUTABLE_EVIDENCE]
    if RUNNER_LOG_PATH.is_file():
        paths.append(RUNNER_LOG_PATH)
    return {str(path.relative_to(REPOSITORY_ROOT)): _sha256(path) for path in sorted(paths)}


def _validate_preflight() -> None:
    try:
        report = direct_additional_validate.validate(PREFLIGHT_DIR, expected_mode="fake")
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        raise FinalizationRefused(f"frozen no-model preflight does not validate: {exc}") from exc
    if (report.get("runner_identity") or {}).get("files_sha256") != RUNNER_IDENTITY_SHA256:
        raise FinalizationRefused("preflight runner identity differs")


def _validate_initial(root: Path) -> InitialState:
    progress = _read_json(root / "progress.json")
    ledger = _read_json(root / "budget-ledger.json")
    outcome = _read_json(root / "OUTCOME.json")
    if (
        progress.get("benchmark_id") != BENCHMARK_ID
        or progress.get("mode") != "real"
        or progress.get("planned_cells") != list(EXPECTED_CELLS)
        or progress.get("status") != "fail_closed"
        or progress.get("stop")
        != {"cell_id": CAP_CELL, "reason": f"native request identity differs from gateway trace for {CAP_CELL}", "type": "RuntimeError"}
        or progress.get("budget") != ledger
        or outcome.get("benchmark_id") != BENCHMARK_ID
        or outcome.get("mode") != "real"
        or outcome.get("status") != "fail_closed"
        or outcome.get("checkpointed_cells") != CAP_INDEX
        or outcome.get("planned_cells") != len(EXPECTED_CELLS)
        or outcome.get("stop") != progress.get("stop")
    ):
        raise FinalizationRefused("campaign is not the exact recoverable cap-stop state")
    if (root / CAP_RECEIPT_NAME).exists() or (root / "cells" / CAP_CELL / "CHECKPOINT.json").exists():
        raise FinalizationRefused("cap-stop output already exists without a completed transaction")
    _validate_runner_identity(progress)
    _validate_preflight()
    _validate_prior_cells(root, progress)
    _validate_zero_retries_and_identity(root, EXPECTED_CELLS[: CAP_INDEX + 1])
    _validate_ledger(root, ledger, finalized=False)
    checkpoint = _validate_cap_cell(root)
    return InitialState(progress, ledger, outcome, checkpoint, _immutable_hashes(root))


def _final_states(initial: InitialState, finalized_at: float) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    ledger = deepcopy(initial.ledger)
    cap_entry = ledger["cells"][CAP_CELL]
    cap_entry["status"] = "cap_exceeded"
    cap_entry["finished_at"] = initial.checkpoint["timing"]["launcher_finished_at"]
    ledger["updated_at"] = finalized_at

    progress = deepcopy(initial.progress)
    progress["cells"].append(initial.checkpoint)
    progress["status"] = "fail_closed"
    progress["stop"] = deepcopy(FINAL_STOP)
    progress["budget"] = ledger
    progress["finished_at"] = finalized_at
    progress["updated_at"] = finalized_at

    outcome = deepcopy(initial.outcome)
    outcome["status"] = "fail_closed"
    outcome["checkpointed_cells"] = CAP_INDEX + 1
    outcome["stop"] = deepcopy(FINAL_STOP)
    return ledger, progress, outcome


def _state_hashes(root: Path) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for name, relative in _STATE_PATHS.items():
        path = root / relative
        hashes[name] = _sha256(path) if path.is_file() else None
    return hashes


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    lock_path = root / ".cap-stop.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FinalizationRefused("another cap-stop finalizer holds the lock") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _commit_cap_stop(root: Path, initial: InitialState) -> dict[str, Any]:
    finalized_at = time.time()
    ledger, progress, outcome = _final_states(initial, finalized_at)
    target = {
        "budget-ledger.json": ledger,
        "progress.json": progress,
        "OUTCOME.json": outcome,
        "cap_checkpoint": initial.checkpoint,
    }
    before = _state_hashes(root)
    after = {name: _encoded_hash(value) for name, value in target.items()}
    receipt = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "status": "prepared",
        "finalized_at": finalized_at,
        "cap_cell": CAP_CELL,
        "unrun_cell": FINAL_CELL,
        "reason": CAP_REASON,
        "effect": "append the consumed cap cell, preserve the cap block, and prohibit the final ThinHarness cell",
        "before_state_sha256": before,
        "after_state_sha256": after,
        "immutable_evidence_sha256": initial.immutable_evidence,
        "frozen_runner_files_sha256": RUNNER_IDENTITY_SHA256,
        "facts": {
            "upstream_requests": EXPECTED_UPSTREAM_REQUESTS,
            "native_model_attempts": EXPECTED_NATIVE_ATTEMPTS,
            "locally_denied_attempts": EXPECTED_LOCAL_DENIALS,
            "verifier_reward": 0,
            "cell_spend_usd": str(EXPECTED_CAP_SPEND),
            "cap_usd": str(PER_CELL_CAP_USD),
            "overshoot_usd": str(EXPECTED_OVERSHOOT),
            "total_spend_usd": str(EXPECTED_TOTAL_SPEND),
        },
        "target_state": target,
    }
    atomic_json(root / CAP_RECEIPT_NAME, receipt)
    for name, value in target.items():
        atomic_json(root / _STATE_PATHS[name], value)
    if _state_hashes(root) != after:
        raise FinalizationRefused("cap-stop state hashes do not match the prepared transaction")
    receipt["status"] = "completed"
    receipt.pop("target_state")
    atomic_json(root / CAP_RECEIPT_NAME, receipt)
    return receipt


def _resume_prepared(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    before = receipt.get("before_state_sha256") or {}
    after = receipt.get("after_state_sha256") or {}
    current = _state_hashes(root)
    if set(before) != set(_STATE_PATHS) or set(after) != set(_STATE_PATHS):
        raise FinalizationRefused("prepared cap-stop receipt has incomplete state hashes")
    if any(current[name] not in {before[name], after[name]} for name in _STATE_PATHS):
        raise FinalizationRefused("partial cap-stop state differs from the durable transaction")
    target = receipt.get("target_state")
    if not isinstance(target, dict) or set(target) != set(_STATE_PATHS):
        raise FinalizationRefused("prepared cap-stop receipt lacks target state")
    for name, value in target.items():
        if not isinstance(value, dict) or _encoded_hash(value) != after[name]:
            raise FinalizationRefused("prepared cap-stop target state differs")
        atomic_json(root / _STATE_PATHS[name], value)
    if _state_hashes(root) != after:
        raise FinalizationRefused("resumed cap-stop state hashes differ")
    receipt["status"] = "completed"
    receipt.pop("target_state")
    atomic_json(root / CAP_RECEIPT_NAME, receipt)
    return receipt


def _validate_final_state(root: Path) -> dict[str, Any]:
    receipt = _read_json(root / CAP_RECEIPT_NAME)
    if (
        receipt.get("schema_version") != 1
        or receipt.get("benchmark_id") != BENCHMARK_ID
        or receipt.get("status") != "completed"
        or receipt.get("cap_cell") != CAP_CELL
        or receipt.get("unrun_cell") != FINAL_CELL
        or receipt.get("reason") != CAP_REASON
        or receipt.get("frozen_runner_files_sha256") != RUNNER_IDENTITY_SHA256
        or receipt.get("facts")
        != {
            "upstream_requests": EXPECTED_UPSTREAM_REQUESTS,
            "native_model_attempts": EXPECTED_NATIVE_ATTEMPTS,
            "locally_denied_attempts": EXPECTED_LOCAL_DENIALS,
            "verifier_reward": 0,
            "cell_spend_usd": str(EXPECTED_CAP_SPEND),
            "cap_usd": str(PER_CELL_CAP_USD),
            "overshoot_usd": str(EXPECTED_OVERSHOOT),
            "total_spend_usd": str(EXPECTED_TOTAL_SPEND),
        }
    ):
        raise FinalizationRefused("completed cap-stop receipt identity or facts differ")
    if receipt.get("after_state_sha256") != _state_hashes(root):
        raise FinalizationRefused("completed cap-stop state hashes differ")
    immutable = receipt.get("immutable_evidence_sha256")
    if not isinstance(immutable, dict) or not immutable:
        raise FinalizationRefused("cap-stop receipt has no immutable evidence hashes")
    for relative, expected in immutable.items():
        if not isinstance(relative, str) or not isinstance(expected, str) or _sha256(REPOSITORY_ROOT / relative) != expected:
            raise FinalizationRefused(f"cap-stop immutable evidence differs: {relative}")
    progress = _read_json(root / "progress.json")
    ledger = _read_json(root / "budget-ledger.json")
    outcome = _read_json(root / "OUTCOME.json")
    if (
        progress.get("benchmark_id") != BENCHMARK_ID
        or progress.get("mode") != "real"
        or progress.get("status") != "fail_closed"
        or progress.get("planned_cells") != list(EXPECTED_CELLS)
        or progress.get("stop") != FINAL_STOP
        or progress.get("budget") != ledger
        or outcome.get("status") != "fail_closed"
        or outcome.get("checkpointed_cells") != CAP_INDEX + 1
        or outcome.get("planned_cells") != len(EXPECTED_CELLS)
        or outcome.get("stop") != FINAL_STOP
    ):
        raise FinalizationRefused("final fail-closed control state differs")
    _validate_runner_identity(progress)
    _validate_preflight()
    _validate_prior_cells(root, progress)
    _validate_zero_retries_and_identity(root, EXPECTED_CELLS[: CAP_INDEX + 1])
    _validate_ledger(root, ledger, finalized=True)
    cap = _validate_cap_cell(root)
    if progress["cells"][CAP_INDEX] != cap or _read_json(root / "cells" / CAP_CELL / "CHECKPOINT.json") != cap:
        raise FinalizationRefused("cap checkpoint does not reproduce from preserved evidence")
    return receipt


def _latency(checkpoint: dict[str, Any]) -> dict[str, str | None]:
    timing = checkpoint.get("timing") or {}
    start = timing.get("launcher_started_at")
    finish = timing.get("launcher_finished_at")
    wall = float(finish) - float(start) if isinstance(start, int | float) and isinstance(finish, int | float) else None
    native = timing.get("native_agent_seconds")
    request_values = [value for value in timing.get("request_seconds") or [] if isinstance(value, int | float)]
    verifier = timing.get("verifier") or {}
    verifier_seconds = None
    if isinstance(verifier, dict) and isinstance(verifier.get("started_at"), str) and isinstance(verifier.get("finished_at"), str):
        verifier_seconds = _seconds(verifier["started_at"], verifier["finished_at"])
    return {
        "launcher_wall_seconds": f"{wall:.6f}" if wall is not None else None,
        "native_agent_seconds": f"{float(native):.6f}" if isinstance(native, int | float) else None,
        "upstream_request_seconds": f"{sum(request_values):.6f}" if request_values else None,
        "verifier_seconds": f"{verifier_seconds:.6f}" if verifier_seconds is not None else None,
    }


def _cell_row(root: Path, checkpoint: dict[str, Any], strata: dict[str, str]) -> dict[str, Any]:
    cell_id = str(checkpoint["cell_id"])
    audit = _read_jsonl(root / "cells" / cell_id / "gateway-audit.jsonl", decimals=True)
    cost = _request_cost(audit)
    usage = {name: int((checkpoint.get("usage") or {}).get(name) or 0) for name in (
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )}
    tools = sum(int(batch.get("tool_calls_in_response") or 0) for batch in checkpoint.get("batching") or [])
    return {
        "cell_id": cell_id,
        "task": checkpoint["task"],
        "harness": checkpoint["harness"],
        "stratum": strata[str(checkpoint["task"])],
        "status": checkpoint["status"],
        "verifier_reward": checkpoint.get("reward"),
        "verifier_outcome_available": isinstance(checkpoint.get("reward"), int | float),
        "upstream_requests": len(audit),
        "successful_upstream_requests": sum(item.get("status") == 200 for item in audit),
        "native_model_attempts": checkpoint.get("native_model_attempt_count"),
        "locally_denied_attempts": checkpoint.get("locally_denied_attempt_count", 0),
        "tools": tools,
        "usage": usage,
        "latency": _latency(checkpoint),
        "api_equivalent_cost_usd": f"{cost:.8f}",
        "provider_reported_actual_cash_usd": (checkpoint.get("cost") or {}).get("actual_cash_total"),
        "traces": checkpoint.get("traces"),
    }


def _group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usage_names = tuple((rows[0].get("usage") or {}).keys()) if rows else (
        "input_tokens",
        "ordinary_input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    rewards = [Decimal(str(row["verifier_reward"])) for row in rows if isinstance(row.get("verifier_reward"), int | float)]
    latency: dict[str, dict[str, Any]] = {}
    for name in ("launcher_wall_seconds", "native_agent_seconds", "upstream_request_seconds", "verifier_seconds"):
        values = [Decimal(row["latency"][name]) for row in rows if row.get("latency", {}).get(name) is not None]
        latency[name] = {"total_seconds": f"{sum(values, Decimal(0)):.6f}", "observations": len(values)}
    return {
        "observed_cells": len(rows),
        "status_counts": dict(sorted(Counter(str(row["status"]) for row in rows).items())),
        "score": {"reward_sum": f"{sum(rewards, Decimal(0)):.0f}", "verifier_outcomes": len(rewards)},
        "upstream_requests": sum(int(row["upstream_requests"]) for row in rows),
        "successful_upstream_requests": sum(int(row["successful_upstream_requests"]) for row in rows),
        "locally_denied_attempts": sum(int(row["locally_denied_attempts"]) for row in rows),
        "tools": sum(int(row["tools"]) for row in rows),
        "usage": {name: sum(int(row["usage"][name]) for row in rows) for name in usage_names},
        "latency": latency,
        "api_equivalent_cost_usd": f"{sum((Decimal(row['api_equivalent_cost_usd']) for row in rows), Decimal(0)):.8f}",
        "provider_reported_actual_cash_observations": sum(row["provider_reported_actual_cash_usd"] is not None for row in rows),
        "provider_reported_actual_cash_total_usd": None,
    }


def _pair_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_cell = {row["cell_id"]: row for row in rows}
    pairs: list[dict[str, Any]] = []
    for task in (cell.rsplit("--", 1)[0] for cell in EXPECTED_CELLS[::2]):
        pi = by_cell.get(f"{task}--pi")
        thin = by_cell.get(f"{task}--thinharness")
        if (
            pi is None
            or thin is None
            or not isinstance(pi.get("verifier_reward"), int | float)
            or not isinstance(thin.get("verifier_reward"), int | float)
        ):
            continue
        pairs.append(
            {
                "task": task,
                "stratum": pi["stratum"],
                "pi": pi,
                "thinharness": thin,
                "pi_minus_thinharness": {
                    "reward": float(pi["verifier_reward"]) - float(thin["verifier_reward"]),
                    "upstream_requests": pi["upstream_requests"] - thin["upstream_requests"],
                    "tools": pi["tools"] - thin["tools"],
                    "launcher_wall_seconds": (
                        f"{Decimal(pi['latency']['launcher_wall_seconds']) - Decimal(thin['latency']['launcher_wall_seconds']):.6f}"
                    ),
                    "api_equivalent_cost_usd": (
                        f"{Decimal(pi['api_equivalent_cost_usd']) - Decimal(thin['api_equivalent_cost_usd']):.8f}"
                    ),
                },
            }
        )
    return pairs


def build_report(root: Path = ARTIFACT_DIR) -> dict[str, Any]:
    progress = _read_json(root / "progress.json")
    selection = _read_json(SELECTION_PATH)
    strata = {str(item["task"]): str(item["selection_stratum"]) for item in selection["selected"]}
    rows = [_cell_row(root, checkpoint, strata) for checkpoint in progress["cells"]]
    rows.append(
        {
            "cell_id": FINAL_CELL,
            "task": "make-doom-for-mips",
            "harness": "thinharness",
            "stratum": "hard",
            "status": "unrun_prior_cap_breach",
            "verifier_reward": None,
            "verifier_outcome_available": False,
            "upstream_requests": 0,
            "successful_upstream_requests": 0,
            "native_model_attempts": 0,
            "locally_denied_attempts": 0,
            "tools": 0,
            "usage": None,
            "latency": None,
            "api_equivalent_cost_usd": None,
            "provider_reported_actual_cash_usd": None,
            "traces": None,
        }
    )
    observed = rows[:-1]
    by_harness = {harness: _group([row for row in observed if row["harness"] == harness]) for harness in ("pi", "thinharness")}
    by_harness["thinharness"]["unrun_cells"] = 1
    by_harness["pi"]["unrun_cells"] = 0
    by_stratum = {label: _group([row for row in observed if row["stratum"] == label]) for label in ("easy", "medium", "hard")}
    historical = _read_json(HISTORICAL_REPORT_PATH).get("historical_four_task_post_fix_sample")
    if not isinstance(historical, dict):
        raise FinalizationRefused("historical four-task section is absent")
    cap_receipt = root / CAP_RECEIPT_NAME
    recovery_receipt = root / recovery.RECEIPT_NAME
    return {
        "schema_version": 2,
        "benchmark_id": BENCHMARK_ID,
        "mode": "real",
        "status": "fail_closed",
        "planned_cells": len(EXPECTED_CELLS),
        "consumed_cells": CAP_INDEX + 1,
        "normal_completions": 17,
        "score": {"reward_sum": "15", "verifier_outcomes": 18},
        "policy_refusals": 1,
        "unrun_cells": 1,
        "cells": rows,
        "aggregate": _group(observed),
        "by_harness": by_harness,
        "by_empirical_stratum": by_stratum,
        "paired_results": _pair_results(observed),
        "paired_result_policy": "include a task only when both cells have verifier outcomes",
        "failures": [
            {
                "cell_id": "torch-pipeline-parallelism--pi",
                "type": "verifier_failure",
                "status": "completed",
                "verifier_reward": 0,
            },
            {
                "cell_id": "torch-pipeline-parallelism--thinharness",
                "type": "verifier_failure",
                "status": "completed",
                "verifier_reward": 0,
            },
            {
                "cell_id": recovery.POLICY_CELL,
                "type": "provider_policy_refusal",
                "status": "model_attempt_failed",
                "verifier_reward": None,
                "provider_status": 400,
                "provider_error_code": "cyber_policy",
                "credit_exhausted": False,
            },
            {
                "cell_id": CAP_CELL,
                "type": "cap_exceeded_with_verifier_failure",
                "status": "cap_exceeded",
                "verifier_reward": 0,
            },
            {
                "cell_id": FINAL_CELL,
                "type": "unrun_due_to_prior_cap_breach",
                "status": "unrun_prior_cap_breach",
                "verifier_reward": None,
            },
        ],
        "cap_stop": {
            "cell_id": CAP_CELL,
            "status": "cap_exceeded",
            "per_cell_cap_usd": "3.00",
            "spent_usd": "3.02611250",
            "overshoot_usd": "0.02611250",
            "upstream_requests": 41,
            "successful_upstream_requests": 41,
            "native_model_attempts": 42,
            "locally_denied_attempts": 1,
            "local_denial_had_upstream_marker": False,
            "verifier_reward": 0,
            "campaign_block_preserved": True,
            "final_cell": {"cell_id": FINAL_CELL, "status": "unrun_prior_cap_breach"},
        },
        "spend": {
            "currency": "USD",
            "basis": "API-equivalent frozen token schedule",
            "price_usd_per_million_tokens": PRICES,
            "total_api_equivalent_usd": "16.89269325",
            "provider_reported_actual_cash_observations": 0,
            "provider_reported_actual_cash_total_usd": None,
            "actual_cash_availability": "unavailable; no successful OpenAI response reported actual cash",
        },
        "identities": {
            "runner_files_sha256": RUNNER_IDENTITY_SHA256,
            "runner": progress.get("runner_identity"),
            "source": progress.get("source_identity"),
            "dataset": progress.get("dataset"),
            "model": progress.get("model"),
            "retries": {"agent": 0, "harbor": 0, "model": 0, "provider": 0, "transport": 0},
        },
        "receipts": {
            "recovery": {"path": str(recovery_receipt.relative_to(REPOSITORY_ROOT)), "sha256": _sha256(recovery_receipt)},
            "cap_stop": {"path": str(cap_receipt.relative_to(REPOSITORY_ROOT)), "sha256": _sha256(cap_receipt)},
            "recovery_validation_note": (
                "The recovery receipt's cell and preflight hashes remain exact. Its progress.jsonl, SUMMARY.json, and "
                "SHA256SUMS.json hashes are historical because the receipt explicitly authorized later cells; the cap-stop receipt "
                "hashes all resulting paid evidence."
            ),
        },
        "historical_four_task_post_fix_sample": {
            **historical,
            "section_role": "separate historical evidence; excluded from every additional-10 total",
            "source_report": str(HISTORICAL_REPORT_PATH.relative_to(REPOSITORY_ROOT)),
            "source_report_sha256": _sha256(HISTORICAL_REPORT_PATH),
        },
        "scope_limit": (
            "Descriptive results for this frozen bounded campaign only. The cap stopped the campaign before the final cell, "
            "so the result is not a complete ten-task matched sample and is not a population ranking."
        ),
        "reproduce": "uv run python -m tbench.direct_additional_finalize check",
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_handoff(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    pi = report["by_harness"]["pi"]
    thin = report["by_harness"]["thinharness"]
    return (
        "# Additional ten-task direct benchmark handoff\n\n"
        "Status: fail-closed at the per-cell cap. Nineteen cells were consumed. Seventeen completed normally, one ended in a "
        "non-credit `cyber_policy` refusal without a verifier, and `make-doom-for-mips--pi` ended `cap_exceeded` with verifier reward 0. "
        "`make-doom-for-mips--thinharness` was not run.\n\n"
        f"The verifier score is 15 over 18 outcomes. Pi scored {pi['score']['reward_sum']} over "
        f"{pi['score']['verifier_outcomes']} outcomes; ThinHarness scored {thin['score']['reward_sum']} over "
        f"{thin['score']['verifier_outcomes']} outcomes. The run used "
        f"{aggregate['upstream_requests']} upstream requests, {aggregate['tools']} native tool calls, and USD "
        f"{aggregate['api_equivalent_cost_usd']} API-equivalent spend. Actual cash is unavailable.\n\n"
        "The cap cell used 41 successful upstream requests but recorded 42 native attempts. Attempt 42 was denied locally before an "
        "upstream marker. Cell spend was USD 3.02611250, which exceeded the USD 3.00 cap by USD 0.02611250. The durable budget block "
        "remains set.\n\n"
        f"Machine report: [`reports/{REPORT_PATH.name}`](../reports/{REPORT_PATH.name}). Cap receipt: "
        f"[`artifacts/{BENCHMARK_ID}/{CAP_RECEIPT_NAME}`]({BENCHMARK_ID}/{CAP_RECEIPT_NAME}). Full evidence: "
        f"[`artifacts/{BENCHMARK_ID}/`]({BENCHMARK_ID}/). Reproduce with `uv run python -m tbench.direct_additional_finalize check`.\n\n"
        "The report includes exact cell outcomes, harness and empirical-stratum totals, eight paired results with two verifier outcomes, "
        "all failures, identities, hashes, traces, the recovery receipt, and the separate historical four-task post-fix sample. Do not "
        "generalize this incomplete matched campaign.\n"
    )


def _write_hashes(root: Path) -> dict[str, str]:
    hashes = {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"SHA256SUMS.json", ".cap-stop.lock"}
    }
    atomic_json(root / "SHA256SUMS.json", hashes)
    return hashes


def _validate_outputs(root: Path) -> dict[str, Any]:
    report = build_report(root)
    rendered = render_report(report)
    if (root / "SUMMARY.json").read_text(encoding="utf-8") != rendered or REPORT_PATH.read_text(encoding="utf-8") != rendered:
        raise FinalizationRefused("final aggregate report does not reproduce")
    if HANDOFF_PATH.read_text(encoding="utf-8") != render_handoff(report):
        raise FinalizationRefused("final handoff does not reproduce")
    direct_additional_validate.validate_hashes(root)
    aggregate = report["aggregate"]
    if (
        report["score"] != {"reward_sum": "15", "verifier_outcomes": 18}
        or report["normal_completions"] != 17
        or report["policy_refusals"] != 1
        or report["unrun_cells"] != 1
        or aggregate["api_equivalent_cost_usd"] != "16.89269325"
        or aggregate["upstream_requests"] != 298
        or len(report["paired_results"]) != 8
    ):
        raise FinalizationRefused("final bounded aggregate facts do not reconcile")
    return report


def finalize(root: Path = ARTIFACT_DIR) -> dict[str, Any]:
    root = root.resolve()
    with _lock(root):
        receipt_path = root / CAP_RECEIPT_NAME
        if receipt_path.is_file():
            receipt = _read_json(receipt_path)
            if receipt.get("status") == "prepared":
                _resume_prepared(root, receipt)
            elif receipt.get("status") != "completed":
                raise FinalizationRefused("existing cap-stop receipt is not resumable")
        else:
            _commit_cap_stop(root, _validate_initial(root))
        _validate_final_state(root)
        report = build_report(root)
        atomic_json(root / "SUMMARY.json", report)
        atomic_json(REPORT_PATH, report)
        HANDOFF_PATH.write_text(render_handoff(report), encoding="utf-8")
        _write_hashes(root)
    return _validate_outputs(root)


def check(root: Path = ARTIFACT_DIR) -> dict[str, Any]:
    root = root.resolve()
    _validate_final_state(root)
    return _validate_outputs(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-model cap-stop finalizer for the bounded additional ten-task campaign")
    parser.add_argument("command", choices=("finalize", "check"))
    parser.add_argument("root", nargs="?", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args()
    report = finalize(args.root) if args.command == "finalize" else check(args.root)
    print(
        json.dumps(
            {
                "status": report["status"],
                "consumed_cells": report["consumed_cells"],
                "score": report["score"],
                "total_api_equivalent_usd": report["spend"]["total_api_equivalent_usd"],
                "cap_stop": report["cap_stop"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
