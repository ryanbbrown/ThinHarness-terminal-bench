"""Static checks for the empirical ten-task runner."""

from __future__ import annotations

import ast
from pathlib import Path

from . import direct_additional_launch, direct_additional_validate
from .direct_additional_constants import EXPECTED_CELLS, PREFLIGHT_DIR


def check() -> None:
    direct_additional_launch._validate_frozen_inputs(PREFLIGHT_DIR)
    if len(EXPECTED_CELLS) != 20:
        raise RuntimeError("runner does not contain exactly 20 frozen cells")
    source = Path("tbench/direct_additional_launch.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    if not any(isinstance(node.func, ast.Attribute) and node.func.attr == "_run_cell" for node in calls):
        raise RuntimeError("runner does not reuse the validated direct cell architecture")
    paid = Path("scripts/run-direct-openai-additional-10.sh").read_text(encoding="utf-8")
    for marker in ("doppler run", "--only-secrets OPENAI_API_KEY", "--no-fallback", "tbench.direct_additional_launch run"):
        if marker not in paid:
            raise RuntimeError(f"secure paid launcher marker is absent: {marker}")
    preflight = Path("scripts/direct-openai-additional-10-preflight.sh").read_text(encoding="utf-8")
    if "tbench.direct_additional_launch preflight" not in preflight or "doppler" in preflight.lower():
        raise RuntimeError("no-model preflight launcher boundary differs")
    if PREFLIGHT_DIR.exists():
        direct_additional_validate.validate(PREFLIGHT_DIR, expected_mode="fake")


def main() -> int:
    check()
    print("additional ten-task runner boundaries passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
