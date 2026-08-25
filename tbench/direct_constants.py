"""Frozen inputs for the direct-OpenAI 20-task pairwise run."""


from .constants import MODEL_ID, PROMPT_PATH, PROMPT_SHA256, REPOSITORY_ROOT

BENCHMARK_ID = "direct-openai-20task-pairwise"
DATASET_NAME = "terminal-bench/terminal-bench-2-1"
DATASET_DIGEST = "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a"
HARBOR_VERSION = "0.21.0"
PI_VERSION = "0.84.2"
THINHARNESS_VERSION = "0.7.0"
THINHARNESS_COMMIT = "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef"
MODEL = MODEL_ID
REASONING = {"effort": "xhigh", "summary": "auto"}
TEXT = {"verbosity": "low"}
PRICES = {"ordinary_input": 5.0, "cached_input": 0.5, "cache_write": 6.25, "output": 30.0}
SELECTION_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-20task-selection.json"
SETTINGS_PATH = REPOSITORY_ROOT / "configs" / "direct-openai-20task-settings.json"
PI_SCHEMAS_PATH = REPOSITORY_ROOT / "configs" / "pi-native-tool-schemas.json"
THIN_SCHEMAS_PATH = REPOSITORY_ROOT / "configs" / "native-tool-schemas.json"
DIRECT_PROMPT_PATH = PROMPT_PATH
DIRECT_PROMPT_SHA256 = PROMPT_SHA256
ARTIFACT_DIR = REPOSITORY_ROOT / "artifacts" / BENCHMARK_ID
PREFLIGHT_DIR = REPOSITORY_ROOT / "artifacts" / f"{BENCHMARK_ID}-preflight"
JOBS_DIR = REPOSITORY_ROOT / "jobs" / BENCHMARK_ID
PREFLIGHT_JOBS_DIR = REPOSITORY_ROOT / "jobs" / f"{BENCHMARK_ID}-preflight"
RUNS_DIR = REPOSITORY_ROOT / "runs" / BENCHMARK_ID
REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}.json"
PREFLIGHT_REPORT_PATH = REPOSITORY_ROOT / "reports" / f"{BENCHMARK_ID}-preflight.json"
CONTAINER_STAGE = "/opt/thinharness-terminal-bench-direct"
CONTAINER_LOGS = "/logs/agent"
CONTAINER_ROOT = "/app"
SOURCE_BUNDLE_ENV = "TB_THINHARNESS_SOURCE_BUNDLE"
SOURCE_BUNDLE_SHA_ENV = "TB_THINHARNESS_SOURCE_BUNDLE_SHA256"
LOCAL_SOURCE_ENV = "TB_THINHARNESS_LOCAL_SOURCE"
GATEWAY_URL_ENV = "TB_DIRECT_GATEWAY_URL"
GATEWAY_TOKEN_ENV = "TB_DIRECT_GATEWAY_TOKEN"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
UPSTREAM_URL = "https://api.openai.com/v1/responses"
ATTEMPTS = 1
CONCURRENCY = 1
RETRIES = 0
MAX_MODEL_REQUESTS = 64
MAX_TOOL_CALLS = 128


def selection() -> dict:
    """Load the frozen selection."""
    import json

    return json.loads(SELECTION_PATH.read_text(encoding="utf-8"))


TASKS = tuple(item["task"] for item in selection()["selected"])
HARNESSES = ("pi", "thinharness")
EXPECTED_CELLS = tuple(f"{task}--{harness}" for task in TASKS for harness in HARNESSES)
