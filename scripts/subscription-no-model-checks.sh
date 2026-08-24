#!/usr/bin/env bash
set -euo pipefail
uv run --extra dev pytest tests/test_subscription_*.py
uv run --extra dev ruff check tbench/subscription_*.py tests/test_subscription_*.py
uv run --extra dev pyright
uv run python -m tbench.repository_checks
