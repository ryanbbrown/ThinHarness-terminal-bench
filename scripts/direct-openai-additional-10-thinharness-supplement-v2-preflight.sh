#!/usr/bin/env bash
set -euo pipefail

if env | grep -Eq '^[A-Za-z0-9_]+_API_KEY=.+$'; then
  printf '%s\n' 'API credentials are forbidden during the v2 no-model preflight.' >&2
  exit 2
fi
if [[ -z "${TB_THINHARNESS_LOCAL_SOURCE:-}" ]]; then
  printf '%s\n' 'TB_THINHARNESS_LOCAL_SOURCE must name the clean canonical ThinHarness checkout.' >&2
  exit 2
fi
exec uv run python -m tbench.direct_supplement_v2 preflight
