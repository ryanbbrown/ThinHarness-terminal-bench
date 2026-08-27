#!/usr/bin/env bash
set -euo pipefail

uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run python -m tbench.repository_checks
uv run python -m tbench.direct_checks
uv run python -m tbench.direct_additional check
uv run python -m tbench.direct_supplement check
uv run python -m tbench.direct_supplement_finalize check
uv run python -m tbench.direct_supplement_v2 check
uv run python -m tbench.model_extraction_forensics check
git diff --exit-code 40a004c90e0e2ae6e13d40568389389dd7fa0f03 -- \
  artifacts/direct-openai-additional-10-pairwise \
  artifacts/direct-openai-additional-10-thinharness-supplement-v1 \
  configs/direct-openai-additional-10-thinharness-supplement-v1-selection.json \
  configs/direct-openai-additional-10-thinharness-supplement-v1-settings.json \
  reports/direct-openai-additional-10-pairwise.json \
  reports/direct-openai-additional-10-thinharness-supplement-v1.json \
  reports/direct-openai-additional-10-thinharness-supplement-v1-direct-comparison.json
rm -rf dist
uv build
python - <<'PY'
from pathlib import Path
import tarfile
import zipfile

wheels = sorted(Path("dist").glob("*.whl"))
sdists = sorted(Path("dist").glob("*.tar.gz"))
if len(wheels) != 1 or len(sdists) != 1:
    raise SystemExit("expected one wheel and one source distribution")
required = {
    "tbench/direct_supplement_v2.py",
    "tbench/model_extraction_forensics.py",
    "tbench/direct_launch.py",
    "tbench/direct_gateway.py",
    "tbench/direct_container.py",
    "tbench/direct_budget.py",
}
with zipfile.ZipFile(wheels[0]) as archive:
    names = set(archive.namelist())
    if not required <= names:
        raise SystemExit("wheel is missing v2 runtime modules")
    if any(name.startswith(("artifacts/", "evidence/", "jobs/", "runs/", "reports/")) for name in names):
        raise SystemExit("wheel contains evidence or runtime state")
with tarfile.open(sdists[0]) as archive:
    names = set(archive.getnames())
    if not all(any(name.endswith("/" + required_name) for name in names) for required_name in required):
        raise SystemExit("source distribution is missing v2 runtime modules")
print("v2 package contents valid")
PY
uv run python -m tbench.direct_supplement_v2 validate \
  artifacts/direct-openai-additional-10-thinharness-supplement-v2-preflight \
  --mode fake
