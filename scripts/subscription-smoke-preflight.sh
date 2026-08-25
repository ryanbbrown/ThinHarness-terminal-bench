#!/usr/bin/env bash
set -euo pipefail
: "${TB_THINHARNESS_LOCAL_SOURCE:?Set TB_THINHARNESS_LOCAL_SOURCE to a clean ThinHarness checkout containing the pinned commit}"
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY must be unset for the subscription preflight" >&2
  exit 2
fi
uv run python -m tbench.subscription_launch preflight
uv run python -m tbench.subscription_validate finalize-preflight artifacts/codex-subscription-3task-extension-preflight \
  --report reports/codex-subscription-3task-extension-preflight.json >/dev/null
