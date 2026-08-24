#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  echo "Refusing no-model preflight while OPENAI_API_KEY is present" >&2
  exit 2
fi
uv run python -m tbench.launch preflight
