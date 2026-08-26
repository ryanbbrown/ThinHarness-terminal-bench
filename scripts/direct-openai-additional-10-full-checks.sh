#!/usr/bin/env bash
set -euo pipefail

uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev pyright
uv run python -m tbench.repository_checks
uv run python -m tbench.direct_additional check
uv run python -m tbench.direct_additional_runner_checks
rm -rf dist
uv build
