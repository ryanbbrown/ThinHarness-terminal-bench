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
  evidence
output="$(mktemp -d)"
trap 'rm -rf "$output"' EXIT
uv run python -m tbench.direct_additional render "$output"
cmp "$output/direct-openai-additional-10-selection.json" configs/direct-openai-additional-10-selection.json
cmp "$output/direct-openai-additional-10-population.json" reports/direct-openai-additional-10-population.json
uv build
uv run python - <<'PY'
import zipfile
from pathlib import Path
wheels = sorted(Path('dist').glob('*.whl'))
if len(wheels) != 1:
    raise SystemExit('expected exactly one wheel')
with zipfile.ZipFile(wheels[0]) as archive:
    names = archive.namelist()
if 'tbench/direct_additional.py' not in names:
    raise SystemExit('no-launch preparation validator is absent from wheel')
if any(name.startswith(('artifacts/', 'evidence/', 'reports/', 'jobs/', 'runs/')) for name in names):
    raise SystemExit('runtime evidence entered wheel')
print('additional ten-task package contents passed')
PY
