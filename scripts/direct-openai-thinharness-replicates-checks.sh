#!/usr/bin/env bash
set -euo pipefail

uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run python -m tbench.repository_checks
uv run python -m tbench.direct_checks
uv build
python - <<'PY'
from pathlib import Path
import zipfile

wheels = sorted(Path('dist').glob('*.whl'))
if len(wheels) != 1:
    raise SystemExit(f'expected one wheel, found {len(wheels)}')
with zipfile.ZipFile(wheels[0]) as archive:
    names = archive.namelist()
    required = {
        'tbench/direct_replicates.py',
        'tbench/dna_analysis.py',
        'tbench/direct_launch.py',
        'tbench/direct_gateway.py',
    }
    if not required <= set(names):
        raise SystemExit('wheel is missing replicate runtime modules')
    forbidden = [name for name in names if name.startswith(('artifacts/', 'reports/', 'jobs/', 'runs/'))]
    if forbidden:
        raise SystemExit(f'wheel contains runtime evidence: {forbidden[:3]}')
print('replicate package contents valid')
PY
uv run python -m tbench.dna_analysis --check >/dev/null
uv run python -m tbench.direct_replicates validate artifacts/direct-openai-thinharness-replicates-v1-preflight --mode fake
if [[ -d artifacts/direct-openai-thinharness-replicates-v1 ]]; then
  uv run python -m tbench.direct_replicates validate artifacts/direct-openai-thinharness-replicates-v1 --mode real
fi
