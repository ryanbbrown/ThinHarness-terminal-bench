#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  printf '%s\n' 'Refusing caller-supplied OPENAI_API_KEY; use Doppler only.' >&2
  exit 2
fi
if [[ -z "${TB_THINHARNESS_LOCAL_SOURCE:-}" ]]; then
  printf '%s\n' 'TB_THINHARNESS_LOCAL_SOURCE must name the clean canonical ThinHarness checkout.' >&2
  exit 2
fi
command -v doppler >/dev/null

export TB_DOPPLER_LAUNCH=tb-additional-10-thinharness-supplement-v2
exec env -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY doppler run \
  --project api-keys \
  --config dev_personal \
  --only-secrets OPENAI_API_KEY \
  --no-cache \
  --no-fallback \
  -- uv run python -m tbench.direct_supplement_v2 run
