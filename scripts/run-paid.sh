#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY must already be in the process environment" >&2
  exit 2
fi
uv run python -m tbench.launch paid
