"""Frozen complete native ThinHarness tool-schema contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class SchemaContractError(RuntimeError):
    """The installed native tool surface differs from the frozen contract."""


def schema_sha256(schema: dict[str, Any]) -> str:
    """Hash one complete schema with canonical JSON serialization."""
    encoded = json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_native_tool_schemas(actual: list[dict[str, Any]], expected_path: Path) -> dict[str, str]:
    """Require exact names, ordering, descriptions, and parameter schemas."""
    value = json.loads(expected_path.read_text(encoding="utf-8"))
    expected = value.get("schemas") if isinstance(value, dict) else None
    if not isinstance(expected, list) or not all(isinstance(item, dict) for item in expected):
        raise SchemaContractError("frozen native tool schemas are invalid")
    if actual != expected:
        raise SchemaContractError("installed native tool schemas differ from the frozen complete contract")
    return {str(schema["name"]): schema_sha256(schema) for schema in actual}
