"""Durable JSON writes for restart-safe run control state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def fsync_directory(path: Path) -> None:
    """Persist directory metadata after a create, append, or replace."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    """Replace one JSON file atomically and fsync both file and directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, value: Any, *, mode: int = 0o600) -> None:
    """Append one JSON line and fsync the file and its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, mode)
    fsync_directory(path.parent)
