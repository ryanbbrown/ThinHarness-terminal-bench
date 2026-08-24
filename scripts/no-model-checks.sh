#!/usr/bin/env bash
set -euo pipefail
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run python -m tbench.repository_checks
