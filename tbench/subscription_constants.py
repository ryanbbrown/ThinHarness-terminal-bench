"""Frozen inputs for the Codex-subscription matched smoke."""

from pathlib import Path

from .constants import MODEL_ID, PROMPT_PATH, PROMPT_SHA256, REPOSITORY_ROOT

SMOKE_ID = "codex-subscription-crack-7z-recovery"
DATASET_NAME = "terminal-bench/terminal-bench-2-1"
DATASET_DIGEST = "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a"
THINHARNESS_COMMIT = "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef"
CPROXY_VERSION = "0.1.0"
CPROXY_COMMIT = "ef96cbaea614753171627c059297e163fed0bc53"
CPROXY_UPSTREAM = "https://chatgpt.com/backend-api/codex/responses"
PI_VERSION = "0.84.2"
PI_PACKAGE = "@earendil-works/pi-coding-agent"
PI_NPM_INTEGRITY = "sha512-l4E+B7hgXKWddRo8bC/eSue2aWZjEgJ9xIpf5p0Og+lq8a2TArCwJ0HCoCPCgaBP/tN4zbYH/wOwvx9pJpeLCA=="
NODE_VERSION = "22.23.1"
MODEL = MODEL_ID
REASONING = {"effort": "xhigh", "summary": "auto"}
TEXT = {"verbosity": "low"}
TASKS = ("crack-7z-hash",)
HARNESSES = ("pi", "thinharness")
EXPECTED_CELLS = tuple(f"{task}--{harness}" for task in TASKS for harness in HARNESSES)
SELECTION_PATH = REPOSITORY_ROOT / "configs" / "subscription-recovery-selection.json"
SUBSCRIPTION_PROMPT_PATH = PROMPT_PATH
SUBSCRIPTION_PROMPT_SHA256 = PROMPT_SHA256
SUBSCRIPTION_JOBS_DIR = REPOSITORY_ROOT / "jobs" / SMOKE_ID
SUBSCRIPTION_RUNS_DIR = REPOSITORY_ROOT / "runs" / SMOKE_ID
SUBSCRIPTION_ARTIFACT_DIR = REPOSITORY_ROOT / "artifacts" / SMOKE_ID
SUBSCRIPTION_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{SMOKE_ID}.json"
CONTAINER_STAGE = "/opt/thinharness-terminal-bench-subscription"
CONTAINER_LOGS = "/logs/agent"
CONTAINER_ROOT = "/app"
HARBOR_VERSION = "0.21.0"
ATTEMPTS = 1
CONCURRENCY = 1
RETRIES = 0
MAX_MODEL_REQUESTS = 64
MAX_TOOL_CALLS = 128
GATEWAY_URL_ENV = "TB_SUBSCRIPTION_GATEWAY_URL"
GATEWAY_TOKEN_ENV = "TB_SUBSCRIPTION_GATEWAY_TOKEN"
SOURCE_BUNDLE_ENV = "TB_THINHARNESS_SOURCE_BUNDLE"
SOURCE_BUNDLE_SHA_ENV = "TB_THINHARNESS_SOURCE_BUNDLE_SHA256"
LOCAL_SOURCE_ENV = "TB_THINHARNESS_LOCAL_SOURCE"
CODEX_AUTH_PATH = Path("~/.codex/auth.json").expanduser()
