"""Static package, boundary, selection, and artifact checks for the 40-cell runner."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .direct_constants import (
    EXPECTED_CELLS,
    PI_SCHEMAS_PATH,
    PREFLIGHT_DIR,
    SELECTION_PATH,
    SETTINGS_PATH,
    TASKS,
    THIN_SCHEMAS_PATH,
)
from .direct_validate import validate_finalized_preflight


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check() -> None:
    """Fail if any frozen direct-run boundary or optional artifact differs."""
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    proof = json.loads(SELECTION_PATH.with_name("direct-openai-exclusion-proof.json").read_text(encoding="utf-8"))
    selected = selection.get("selected") or []
    if len(selected) != 20 or len(set(TASKS)) != 20 or selection.get("planned_cells") != 40:
        raise RuntimeError("selection is not exactly 20 tasks and 40 unique cells")
    if selection.get("planned_execution_order") != list(EXPECTED_CELLS):
        raise RuntimeError("selection order differs from task-pair Pi-then-ThinHarness order")
    excluded = set(selection.get("excluded_prior_selected_or_evidenced_tasks") or [])
    if excluded & set(TASKS) or proof.get("result") != "fresh" or proof.get("selected_tasks") != list(TASKS):
        raise RuntimeError("frozen exclusion proof does not establish task freshness")
    keys = [(float(item["expert_time_estimate_min"]), item["memory_mb"], item["agent_timeout_sec"], item["task"]) for item in selected]
    if keys != sorted(keys):
        raise RuntimeError("selected low-cost task order differs from the frozen sort")
    for item in selected:
        for name in ("task_package_digest", "task_toml_sha256", "instruction_sha256", "task_tree_sha256"):
            if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", item.get(name, "")):
                raise RuntimeError(f"selected task hash is invalid: {item.get('task')} {name}")
    if settings["harbor"]["version"] != "0.21.0" or settings["harnesses"]["pi"]["version"] != "0.84.2":
        raise RuntimeError("Harbor or Pi identity differs")
    thin = settings["harnesses"]["thinharness"]
    if thin["version"] != "0.7.0" or thin["commit"] != "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef":
        raise RuntimeError("ThinHarness identity differs")
    if settings["model"]["route"] != "direct https://api.openai.com/v1/responses" or settings["model"]["bridge"] is not None:
        raise RuntimeError("provider route is not direct OpenAI")
    if settings["model"]["model_retries"] != 0 or settings["model"]["transport_retries"] != 0:
        raise RuntimeError("model or transport retries are not zero")
    if settings["harnesses"]["pi"]["tool_schema_file_sha256"] != _sha256(PI_SCHEMAS_PATH):
        raise RuntimeError("frozen Pi native schemas changed")
    if settings["harnesses"]["thinharness"]["tool_schema_file_sha256"] != _sha256(THIN_SCHEMAS_PATH):
        raise RuntimeError("frozen ThinHarness native schemas changed")
    direct_files = [path for path in Path("tbench").glob("direct_*.py")] + [path for path in Path("scripts").glob("*direct-openai*")]
    bridge_markers = ("from " + "cproxy", "chatgpt.com/" + "backend-api", "codex " + "oauth")
    for path in direct_files:
        source = path.read_text(encoding="utf-8").lower()
        if any(marker in source for marker in bridge_markers):
            raise RuntimeError(f"direct runner imports or names a subscription bridge: {path}")
    script = Path("scripts/run-direct-openai-20task.sh").read_text(encoding="utf-8")
    for marker in ("doppler run", "--only-secrets OPENAI_API_KEY", "--no-fallback", "python -m tbench.direct_launch run"):
        if marker not in script:
            raise RuntimeError(f"Doppler launcher boundary is missing: {marker}")
    package = subprocess.run(
        ["uv", "run", "python", "-c", "import tbench.direct_launch,tbench.direct_gateway,tbench.direct_validate"],
        check=False,
        capture_output=True,
        text=True,
    )
    if package.returncode != 0:
        raise RuntimeError(f"direct runner package import failed: {package.stderr}")
    if PREFLIGHT_DIR.exists():
        validate_finalized_preflight(PREFLIGHT_DIR)


def main() -> int:
    check()
    print("direct runner boundary, package, selection, and artifact checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
