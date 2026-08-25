# Direct-OpenAI 20-task pairwise run

## Frozen design

The run contains exactly 20 fresh Terminal-Bench 2.1 tasks and 40 cells. Each task runs first with Pi 0.84.2 and then with native ThinHarness 0.7.0 at `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`. Harbor 0.21.0 uses one attempt, concurrency one, and zero Harbor retries. Both harnesses use the same frozen Pi prompt, `gpt-5.6-sol`, xhigh reasoning, low text verbosity, and native `read`, `bash`, `edit`, and `write` interfaces. ThinHarness keeps sequential tool execution and its owned 1800-second provider timeout. Model, provider, output, tool, and direct transport retries are zero.

`configs/direct-openai-20task-selection.json` freezes task package, task TOML, instruction, and deterministic task-tree hashes, resource metadata, selection order, and the first task outside the selection. `configs/direct-openai-exclusion-proof.json` records all preserved real cells and jobs, all earlier selection/evidence sources, the conservative prior exclusion union, and the absence of every selected name from prior local Git refs. The selection excludes every task named by an earlier selection or evidence manifest, including earlier rejected candidates.

The provider route is only `https://api.openai.com/v1/responses`. It has no cproxy, Codex OAuth, or subscription bridge. The host gateway holds the Doppler-injected key only in memory and gives each task container a random one-cell bearer. It removes all API-key and Doppler variables before Harbor starts. Native Bash never receives the OpenAI key. Gateway traces record complete requests and responses, sanitized response headers, exact usage, the frozen USD 5.00 / 0.50 / 6.25 / 30.00 per-million-token schedule, request timing, and batching. The gateway writes `MODEL_REQUEST_STARTED.jsonl` and fsyncs it before each upstream request.

## Restart and stop policy

`progress.json`, `progress.jsonl`, `OUTCOME.json`, and each cell `CHECKPOINT.json` are written atomically after every cell. Any real cell with a model-request marker is consumed forever, including an interrupted or failed cell. A restart skips it. A failure before the marker is moved to `infrastructure-attempts/` and can run again after the infrastructure fix. Non-credit provider failures consume that cell and continue. Only confirmed `insufficient_quota`, billing-limit, billing-inactive, credit-exhausted, usage-limit, or HTTP 402 responses stop new launches immediately. An unrecoverable pre-request external blocker also stops.

## Completed no-model gate

`artifacts/direct-openai-20task-pairwise-preflight/` contains 40 completed Harbor/Docker cells. Every cell installed its native harness, made two controlled fake-provider responses, called native Bash once, handed the unchanged workspace to the real verifier, received reward zero, and made zero upstream model requests. `behavior-preflight.json` separately proves simulated credit exhaustion and consumed-cell restart decisions. Four recoverable setup/validation attempts are preserved under `infrastructure-attempts/`; the resumed gate completed all cells. `SHA256SUMS.json` covers the full artifact set, and `reports/direct-openai-20task-pairwise-preflight.json` is the aggregate report.

## Authorized real command

Do not run this command during preparation:

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  ./scripts/run-direct-openai-20task.sh
```

The script refuses a caller key. It invokes `doppler run` with project `api-keys`, config `dev_personal`, only `OPENAI_API_KEY`, and no cache or fallback. The Python launcher finalizes the report and hash manifest in the same long-running process.
