#!/usr/bin/env bash
set -euo pipefail
: "${TB_THINHARNESS_LOCAL_SOURCE:?Set TB_THINHARNESS_LOCAL_SOURCE to the clean exact-commit ThinHarness checkout}"
for name in OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY; do
  if [[ -n "${!name:-}" ]]; then
    echo "$name must be unset; this smoke uses only Codex CLI subscription OAuth" >&2
    exit 2
  fi
done
codex login status | grep -F "Logged in using ChatGPT" >/dev/null
uv run python -m tbench.subscription_launch run
uv run python -m tbench.subscription_validate finalize-run artifacts/codex-subscription-4task \
  --report reports/codex-subscription-4task.json >/dev/null
