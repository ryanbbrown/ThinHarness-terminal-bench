"""Frozen inputs for the native ThinHarness Terminal-Bench reproduction."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
HARBOR_VERSION = "0.21.0"
DATASET_NAME = "terminal-bench/terminal-bench-2-1"
DATASET_DIGEST = "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a"
TASK_NAME = "terminal-bench/regex-log"
MODEL_PROVIDER = "openai"
MODEL_ID = "gpt-5.6-sol"
MODEL_REF = f"{MODEL_PROVIDER}/{MODEL_ID}"
OPENAI_BASE_URL = "https://api.openai.com/v1"
REASONING = {"effort": "xhigh", "summary": "auto"}
TEXT = {"verbosity": "low"}
THINHARNESS_REPOSITORY = "https://github.com/ryanbbrown/thinharness.git"
THINHARNESS_COMMIT = "758fcf305e468138b03723760d477444592b1916"
PROMPT_PATH = REPOSITORY_ROOT / "prompts" / "pi-0.84.2-system-prompt.md"
PROMPT_SHA256 = "bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e"
ATTEMPT_BUDGET_USD = 0.50
IMPLEMENTATION_BUDGET_USD = 1.00
ATTEMPTS = 1
CONCURRENCY = 1
HARBOR_RETRIES = 0
PROVIDER_RETRIES = 0
AGENT_OUTPUT_RETRIES = 0
AGENT_TOOL_RETRIES = 0
MAX_MODEL_REQUESTS = 64
MAX_TOOL_CALLS = 128
CONTAINER_ROOT = "/app"
CONTAINER_STAGE = "/opt/thinharness-terminal-bench"
CONTAINER_LOGS = "/logs/agent"
