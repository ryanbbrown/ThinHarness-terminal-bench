"""Static checks for repository boundaries and secret hygiene."""

from __future__ import annotations

import ast
import hashlib
import json
import re

from .constants import PROMPT_PATH, PROMPT_SHA256, REPOSITORY_ROOT, THINHARNESS_COMMIT


def check() -> None:
    """Fail when product code, the proxy adapter, or credential material enters the repository."""
    product_dir = REPOSITORY_ROOT / "thinharness"
    if product_dir.exists():
        raise RuntimeError("ThinHarness product source directory is forbidden")
    forbidden_names = {"adapter.py", "pi_cproxy.py", "pi_direct_openai.py", "pi_native_codex.py"}
    found = sorted(
        path
        for path in REPOSITORY_ROOT.rglob("*.py")
        if path.name in forbidden_names and not any(part in {".venv", "jobs", "runs"} for part in path.parts)
    )
    if found:
        raise RuntimeError(f"superseded runnable adapter path is present: {found}")
    host_source = (REPOSITORY_ROOT / "tbench" / "agent.py").read_text(encoding="utf-8")
    host_tree = ast.parse(host_source)
    import_roots: set[str] = set()
    for node in ast.walk(host_tree):
        if isinstance(node, ast.Import):
            import_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_roots.add(node.module.split(".", 1)[0])
    if "ToolSpec" in host_source or "thinharness" in import_roots:
        raise RuntimeError("host agent must not import ThinHarness or define ToolSpecs")
    forbidden_functions = {"bash", "read", "edit", "write"}
    custom = [
        node.name
        for node in ast.walk(host_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden_functions
    ]
    if custom:
        raise RuntimeError(f"host agent defines model-facing proxy functions: {custom}")
    runner_source = (REPOSITORY_ROOT / "tbench" / "container_runner.py").read_text(encoding="utf-8")
    for required in ("BashPlugin", "FilesystemPlugin", 'root=CONTAINER_ROOT'):
        if required not in runner_source:
            raise RuntimeError(f"container runner is missing native architecture marker: {required}")
    if THINHARNESS_COMMIT not in (REPOSITORY_ROOT / "scripts" / "install-in-container.sh").read_text(encoding="utf-8"):
        raise RuntimeError("container wheel build is not pinned to the canonical commit")
    if hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest() != PROMPT_SHA256:
        raise RuntimeError("frozen prompt hash differs")
    config = json.loads((REPOSITORY_ROOT / "configs" / "frozen-settings.json").read_text(encoding="utf-8"))
    if config["thinharness"]["commit"] != THINHARNESS_COMMIT:
        raise RuntimeError("frozen config ThinHarness commit differs")
    _check_secrets()


def _check_secrets() -> None:
    secret_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"(?i)(?:api[_-]?key|token|secret)\s*[=:]\s*['\"]?[A-Za-z0-9/+_-]{20,}"),
    )
    for path in REPOSITORY_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix in {".pyc", ".whl"}:
            continue
        if any(part in {"jobs", "runs", ".venv", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in secret_patterns:
            if pattern.search(text):
                raise RuntimeError(f"possible credential value in repository file: {path}")


def main() -> int:
    check()
    print("repository boundary and secret checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
