#!/usr/bin/env bash
set -euo pipefail
: "${TB_THINHARNESS_LOCAL_SOURCE:?Set TB_THINHARNESS_LOCAL_SOURCE to a clean ThinHarness checkout containing the pinned commit}"
for name in OPENAI_API_KEY ANTHROPIC_API_KEY OPENROUTER_API_KEY; do
  if [[ -n "${!name:-}" ]]; then
    echo "$name must be unset; this smoke uses only Codex CLI subscription OAuth" >&2
    exit 2
  fi
done
if ! codex_status="$(codex login status 2>&1)"; then
  unset codex_status
  echo "Codex CLI login status check failed" >&2
  exit 2
fi
if [[ "$codex_status" != *"Logged in using ChatGPT"* ]]; then
  unset codex_status
  echo "Codex CLI is not logged in using ChatGPT" >&2
  exit 2
fi
unset codex_status
uv run python -m tbench.subscription_launch run
uv run python -m tbench.subscription_validate finalize-run artifacts/codex-subscription-crack-7z-recovery \
  --report reports/codex-subscription-crack-7z-recovery.json >/dev/null
