#!/usr/bin/env bash
set -euo pipefail

uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run python -m tbench.repository_checks
uv run python -m tbench.direct_additional check
git diff --quiet 70f5a7b69e7cbbcd09464e275b5a75a8821baa7f -- \
  artifacts/direct-openai-20task-pairwise \
  artifacts/direct-openai-thinharness-replicates-v1 \
  evidence/migration-manifest.json \
  evidence/preserved-direct-api-regex-log \
  evidence/dna-insert-prompt-analysis
output="$(mktemp -d)"
trap 'rm -rf "$output"' EXIT
uv run python -m tbench.direct_additional render "$output"
cmp "$output/empirical-task-outcomes.json" evidence/terminal-bench-2-1-official-20260826/derived/empirical-task-outcomes.json
cmp "$output/direct-openai-additional-10-selection.json" configs/direct-openai-additional-10-selection.json
cmp "$output/direct-openai-additional-10-population.json" reports/direct-openai-additional-10-population.json
rm -rf dist
uv build
uv run python - <<'PY'
import tarfile
import zipfile
from pathlib import Path

wheels = sorted(Path("dist").glob("*.whl"))
sdists = sorted(Path("dist").glob("*.tar.gz"))
if len(wheels) != 1 or len(sdists) != 1:
    raise SystemExit("expected exactly one wheel and one sdist")
with zipfile.ZipFile(wheels[0]) as archive:
    wheel_names = archive.namelist()
with tarfile.open(sdists[0]) as archive:
    sdist_names = archive.getnames()
if "tbench/direct_additional.py" not in wheel_names:
    raise SystemExit("no-launch preparation validator is absent from wheel")
for names in (wheel_names, sdist_names):
    if any("/evidence/" in f"/{name}" or "/artifacts/" in f"/{name}" or "/reports/" in f"/{name}" for name in names):
        raise SystemExit("runtime evidence entered a distribution")
print("additional ten-task package contents passed")
PY
