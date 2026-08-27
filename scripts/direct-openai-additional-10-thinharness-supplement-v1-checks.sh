#!/usr/bin/env bash
set -euo pipefail

uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run python -m tbench.repository_checks
uv run python -m tbench.direct_checks
uv run python -m tbench.direct_additional check
uv run python -m tbench.direct_supplement check
git diff --exit-code 0d04252c9b1961cf801544afb5329ab36785200b -- \
  artifacts/direct-openai-additional-10-pairwise \
  jobs/direct-openai-additional-10-pairwise \
  runs/direct-openai-additional-10-pairwise \
  reports/direct-openai-additional-10-pairwise.json
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
with zipfile.ZipFile(wheels[0]) as archive:
    names = set(archive.namelist())
    required = {
        "tbench/direct_supplement.py",
        "tbench/direct_launch.py",
        "tbench/direct_gateway.py",
        "tbench/direct_container.py",
        "tbench/direct_budget.py",
    }
    if not required <= names:
        raise SystemExit("wheel is missing supplemental runtime modules")
    if any(name.startswith(("artifacts/", "jobs/", "runs/", "reports/")) for name in names):
        raise SystemExit("wheel contains runtime evidence")
with tarfile.open(sdists[0]) as archive:
    names = archive.getnames()
    if not any(name.endswith("/tbench/direct_supplement.py") for name in names):
        raise SystemExit("source distribution is missing the supplemental runner")
print("supplemental package contents valid")
PY
uv run python -m tbench.direct_supplement validate \
  artifacts/direct-openai-additional-10-thinharness-supplement-v1-preflight \
  --mode fake
