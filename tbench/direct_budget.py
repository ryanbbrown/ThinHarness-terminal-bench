"""Durable fail-closed API-equivalent budget accounting."""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from .durable import atomic_json

_PRICE = {
    "ordinary_input_tokens": Decimal("5.0"),
    "cached_input_tokens": Decimal("0.5"),
    "cache_write_tokens": Decimal("6.25"),
    "output_tokens": Decimal("30.0"),
}
_MILLION = Decimal(1_000_000)


class BudgetBlocked(RuntimeError):
    """The durable campaign budget cannot authorize more work."""


class DirectBudgetLedger:
    """Reserve one cell at a time and settle every successful response."""

    def __init__(self, path: Path, *, benchmark_id: str, per_cell_cap: Decimal, total_cap: Decimal) -> None:
        self.path = path
        self.benchmark_id = benchmark_id
        self.per_cell_cap = per_cell_cap
        self.total_cap = total_cap
        self._lock = threading.Lock()
        if path.is_file():
            import json

            self.state = json.loads(path.read_text(encoding="utf-8"))
            self._validate_identity()
        else:
            self.state: dict[str, Any] = {
                "schema_version": 1,
                "benchmark_id": benchmark_id,
                "currency": "USD",
                "basis": "frozen API-equivalent token schedule",
                "per_cell_cap_usd": str(per_cell_cap),
                "total_cap_usd": str(total_cap),
                "total_spent_usd": "0",
                "active_cell": None,
                "cells": {},
                "blocked": None,
                "updated_at": time.time(),
            }
            self._write()

    def _validate_identity(self) -> None:
        if (
            self.state.get("benchmark_id") != self.benchmark_id
            or self.state.get("per_cell_cap_usd") != str(self.per_cell_cap)
            or self.state.get("total_cap_usd") != str(self.total_cap)
        ):
            raise BudgetBlocked("budget ledger identity differs from the frozen campaign")

    def _write(self) -> None:
        self.state["updated_at"] = time.time()
        atomic_json(self.path, self.state)

    def _blocked(self) -> None:
        if self.state.get("blocked") is not None:
            raise BudgetBlocked(str(self.state["blocked"].get("reason")))

    def reserve_cell(self, cell_id: str) -> None:
        with self._lock:
            self._blocked()
            cells = self.state["cells"]
            if cell_id in cells:
                raise BudgetBlocked(f"cell already has durable budget state: {cell_id}")
            if self.state.get("active_cell") is not None:
                raise BudgetBlocked("another cell still holds the budget reservation")
            spent = Decimal(self.state["total_spent_usd"])
            if spent + self.per_cell_cap > self.total_cap:
                self._fail_locked(cell_id, "total cap cannot reserve another USD 3.00 cell")
                raise BudgetBlocked("total cap cannot reserve another USD 3.00 cell")
            cells[cell_id] = {
                "status": "reserved",
                "reserved_usd": str(self.per_cell_cap),
                "spent_usd": "0",
                "request_count": 0,
                "consumed": False,
                "reserved_at": time.time(),
            }
            self.state["active_cell"] = cell_id
            self._write()

    def authorize_request(self, cell_id: str) -> None:
        with self._lock:
            self._blocked()
            if self.state.get("active_cell") != cell_id:
                raise BudgetBlocked("request has no active cell reservation")
            cell = self.state["cells"][cell_id]
            cell_spent = Decimal(cell["spent_usd"])
            total_spent = Decimal(self.state["total_spent_usd"])
            committed = total_spent + (self.per_cell_cap - cell_spent)
            if cell_spent >= self.per_cell_cap:
                self._fail_locked(cell_id, "per-cell USD 3.00 cap reached")
                raise BudgetBlocked("per-cell USD 3.00 cap reached")
            if committed > self.total_cap:
                self._fail_locked(cell_id, "total USD 60.00 cap reached")
                raise BudgetBlocked("total USD 60.00 cap reached")

    def request_started(self, cell_id: str) -> None:
        with self._lock:
            if self.state.get("active_cell") != cell_id:
                raise BudgetBlocked("request-start marker has no active reservation")
            cell = self.state["cells"][cell_id]
            cell["request_count"] += 1
            cell["consumed"] = True
            cell["status"] = "consumed"
            cell["last_request_started_at"] = time.time()
            self._write()

    def settle_usage(self, cell_id: str, usage: dict[str, Any]) -> Decimal:
        values: dict[str, int] = {}
        for name in _PRICE:
            value = usage.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                self.fail(cell_id, f"missing or invalid usage: {name}")
                raise BudgetBlocked(f"missing or invalid usage: {name}")
            values[name] = value
        cost = sum((Decimal(values[name]) * price / _MILLION for name, price in _PRICE.items()), Decimal(0))
        with self._lock:
            if self.state.get("active_cell") != cell_id:
                raise BudgetBlocked("usage settlement has no active reservation")
            cell = self.state["cells"][cell_id]
            cell_spent = Decimal(cell["spent_usd"]) + cost
            total_spent = Decimal(self.state["total_spent_usd"]) + cost
            cell["spent_usd"] = str(cell_spent)
            self.state["total_spent_usd"] = str(total_spent)
            cell["last_settlement_usd"] = str(cost)
            if cell_spent >= self.per_cell_cap:
                self._fail_locked(cell_id, "per-cell USD 3.00 cap reached or crossed")
            elif total_spent > self.total_cap:
                self._fail_locked(cell_id, "total USD 60.00 cap crossed")
            else:
                self._write()
        return cost

    def finish_cell(self, cell_id: str) -> None:
        with self._lock:
            if self.state.get("active_cell") != cell_id:
                raise BudgetBlocked("finished cell has no active reservation")
            cell = self.state["cells"][cell_id]
            if not cell.get("consumed"):
                raise BudgetBlocked("a real cell cannot finish without a request-start marker")
            cell["status"] = "settled"
            cell["finished_at"] = time.time()
            self.state["active_cell"] = None
            self._write()

    def release_pre_request(self, cell_id: str, reason: str) -> None:
        with self._lock:
            if self.state.get("active_cell") != cell_id:
                return
            cell = self.state["cells"][cell_id]
            if cell.get("consumed"):
                raise BudgetBlocked("cannot release a consumed cell reservation")
            cell["status"] = "pre_request_infrastructure_failure"
            cell["failure"] = reason
            self.state["active_cell"] = None
            self._write()

    def fail(self, cell_id: str | None, reason: str) -> None:
        with self._lock:
            self._fail_locked(cell_id, reason)

    def _fail_locked(self, cell_id: str | None, reason: str) -> None:
        if self.state.get("blocked") is None:
            self.state["blocked"] = {"cell_id": cell_id, "reason": reason, "at": time.time()}
        self._write()

    @property
    def blocked(self) -> dict[str, Any] | None:
        value = self.state.get("blocked")
        return value if isinstance(value, dict) else None
