# Additional ten-task direct matched preparation

## Decision

This preparation launches nothing. It selects 10 fresh Terminal-Bench 2.1 tasks from accepted verifier outcomes in official merged submissions. It replaces the metadata-weighted selection at commit `5feb120248de092d72771ff7f9630423350daebd`. Resource fields remain only to identify tasks and describe possible run limits.

## Official evidence snapshot

The bounded snapshot is `evidence/terminal-bench-2-1-official-20260826/`. It was fetched at `2026-08-26T01:37:37Z` from:

- official repository: <https://github.com/harbor-framework/terminal-bench-2-1>, `main` commit `7131e4375048a0e408a8fb404b5f499d726b695b`
- official leaderboard: <https://www.tbench.ai/leaderboard/terminal-bench/2.1>
- official Harbor Hub dataset and leaderboard: <https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2-1/latest>

The snapshot preserves all 20 merged `leaderboard/submissions/*.json` files, the official Hub leaderboard response, public per-trial verifier outcomes, public Pi-job search responses, exact source and backing job IDs, and SHA-256 hashes for every raw file. `manifest.json` records source URLs, the fetch time, source commit, dataset digest, identities, coverage, exclusions, and raw and derived source-set hashes. The deterministic derived record is `derived/empirical-task-outcomes.json`.

The current Hub trial IDs differ from the repository promotion trial IDs after a Hub migration. Each usable trial set is bound to its merged submission by exact pull request URL, row ID, agent/model identity, trial count, task digest, and aggregate reward after official disqualifications.

## Included official submissions

Each included submission has all 89 tasks and 5 raw trials per task. A disqualified trial is removed from both the success count and trial count. An accepted errored or unrewarded trial stays in the denominator as a failure.

| Merged submission | Agent | Model | Repository source job | Current Hub backing job | Raw | Disqualified | Accepted |
|---|---|---|---|---|---:|---:|---:|
| `2026-05-01-anthropic-claude-opus-4-7-max-terminus-2.json` | Terminus 2 | Claude Opus 4.7 | `10e2e56b-ed31-5f65-a489-69f78b902adf` | `c8fcaaeb-c49a-413a-9f8d-20bc09c53339` | 445 | 0 | 445 |
| `2026-05-01-gemini-gemini-3-pro-preview-high-gemini-cli.json` | Gemini CLI | Gemini 3 Pro | `fd8707bb-51e8-56fa-8e46-769a82a531ae` | `5b2904c3-c69a-4ad0-b30f-1d77729389f4` | 445 | 2 | 443 |
| `2026-05-01-gemini-gemini-3-pro-preview-high-terminus-2.json` | Terminus 2 | Gemini 3 Pro | `10e2e56b-ed31-5f65-a489-69f78b902adf` | `c8fcaaeb-c49a-413a-9f8d-20bc09c53339` | 445 | 2 | 443 |
| `2026-05-01-glm-5-1-max-claude-code.json` | Claude Code | GLM-5.1 | `fd8707bb-51e8-56fa-8e46-769a82a531ae` | `5b2904c3-c69a-4ad0-b30f-1d77729389f4` | 445 | 0 | 445 |
| `2026-05-01-openai-gpt-5-5-xhigh-codex.json` | Codex | GPT-5.5 | `10e2e56b-ed31-5f65-a489-69f78b902adf` | `c8fcaaeb-c49a-413a-9f8d-20bc09c53339` | 445 | 1 | 444 |
| `2026-05-01-openai-gpt-5-5-xhigh-terminus-2.json` | Terminus 2 | GPT-5.5 | `10e2e56b-ed31-5f65-a489-69f78b902adf` | `c8fcaaeb-c49a-413a-9f8d-20bc09c53339` | 445 | 1 | 444 |
| `2026-05-05-gemini-gemini-3-1-pro-preview-high-gemini-cli.json` | Gemini CLI | Gemini 3.1 Pro | `42cd19c9-42ad-5d79-b033-adf4f879423d` | `d5eae728-5413-4143-b52b-34eb170b045d` | 445 | 1 | 444 |
| `2026-05-05-gemini-gemini-3-1-pro-preview-high-terminus-2.json` | Terminus 2 | Gemini 3.1 Pro | `42cd19c9-42ad-5d79-b033-adf4f879423d` | `d5eae728-5413-4143-b52b-34eb170b045d` | 445 | 2 | 443 |
| `2026-06-05-anthropic-claude-fable-5-high-terminus-2.json` | Terminus 2 | Claude Fable 5 | `ed9327d8-4601-5acb-a7a2-c71dfda0f5dc` | `17f04e4f-1a75-4204-9b75-d042ef0333ec` | 445 | 0 | 445 |
| `2026-06-07-anthropic-claude-fable-5-xhigh-claude-code.json` | Claude Code | Claude Fable 5 | `f9d0318d-30f9-5d6f-bd7f-0ad5acf780d7` | `11efb542-89de-4746-8227-b776c7841a96` | 445 | 1 | 444 |
| `2026-07-09-anthropic-claude-opus-4-8-high-claude-code.json` | Claude Code | Claude Opus 4.8 | `a3019ec2-bc78-5ff6-9cae-d22d62470515` | `67e18b19-c047-4e2f-942b-5849801fae52` | 445 | 0 | 445 |
| `2026-07-09-anthropic-claude-sonnet-5-high-claude-code.json` | Claude Code | Claude Sonnet 5 | `36288ba6-447b-5161-babf-cb46a228436c` | `84ac1a9d-52a7-491b-85fb-dc323231b67f` | 445 | 3 | 442 |
| `2026-07-09-cursor-grok-4-5-none-cursor-cli.json` | Cursor CLI | Grok 4.5 | `d478d2af-5348-575c-b20a-e5a2434dbff7` | `da969e44-7659-4c1a-8041-a5dc9e624ee0` | 445 | 40 | 405 |
| `2026-07-09-openai-muse-spark-1-1-xhigh-mini-swe-agent.json` | mini-SWE-agent | Muse Spark 1.1 | `e15e18db-c8c1-5e9f-9064-1d68975b3c91` | `1c76cec0-5fbd-491c-b1d9-76021e225d4d` | 445 | 0 | 445 |
| `2026-07-11-openai-gpt-5-6-luna-max-codex.json` | Codex | GPT-5.6 Luna | `4860a28f-bc1a-5367-9885-57ff9ccc3a15` | `413ec154-36fb-46f4-a0b2-2111e1c65501` | 445 | 4 | 441 |
| `2026-07-11-openai-gpt-5-6-terra-max-codex.json` | Codex | GPT-5.6 Terra | `84f460e2-f7f8-5249-8e63-d58b197968c7` | `77fc16b9-8db9-4d61-a172-dba037aba20b` | 445 | 1 | 444 |

Four merged files do not enter empirical rates. The Claude Opus 4.7/Claude Code Hub row exposes 445 trials, but its merged file and metric use 447. Three July 10 Codex files have no current official Hub row and their repository job/trial IDs are not publicly readable: GPT-5.6 Luna, Sol, and Terra. The exact-model GPT-5.6 Sol/Codex submission is the closest official comparator, but only its whole-submission metric is available. No per-task Sol rate is inferred.

## Pi evidence and aggregate rate

No merged submission, official Hub leaderboard row, or public Hub job search matched Pi. There is no verified official Pi per-task evidence in this snapshot. The preparation does not infer Pi rates from Codex or any other harness.

For every task, the fallback rate pools integer successes and accepted trials across all 16 included submissions. It does not average submission percentages. This gives every one of the 89 tasks accepted evidence. Eligible task denominators range from 75 to 80 because official disqualifications are excluded. Exact fractions control sorting; the six-decimal value is only for display.

## Fresh population and strata

The complete catalog still has 89 tasks. The unchanged prior-evidence proof excludes 36 tasks, leaving 53 fresh tasks. Resource metadata is descriptive and has no selection weight.

The boundaries were fixed before selection:

- easy: rate at least 3/4
- medium: rate at least 1/2 and below 3/4
- hard: rate below 1/2
- unobserved: zero accepted official trials

Higher success means easier. The eligible counts are 28 easy, 14 medium, 11 hard, and 0 unobserved. Tasks sort by exact rate from high to low, then by task name in ascending byte order. Varying trial counts receive no shrinkage or confidence weight. If evidence had no trials for a task, that task would enter the explicit unobserved stratum instead of receiving a metadata estimate.

Ten tasks divide as evenly as possible across the three nonempty strata: 3 easy, 3 medium, and 4 hard. The extra slot goes by the fixed priority hard, medium, easy, unobserved. Within each stratum, selection uses ranks `floor(i × (N - 1) / (K - 1))` for `i = 0..K-1`.

| Stratum | Task | Accepted success |
|---|---|---:|
| easy | `feal-differential-cryptanalysis` | 80/80 = 1.000000 |
| easy | `llm-inference-batching-scheduler` | 73/80 = 0.912500 |
| easy | `schemelike-metacircular-eval` | 60/80 = 0.750000 |
| medium | `adaptive-rejection-sampler` | 59/80 = 0.737500 |
| medium | `path-tracing-reverse` | 50/77 = 0.649351 |
| medium | `torch-pipeline-parallelism` | 41/76 = 0.539474 |
| hard | `gpt2-codegolf` | 30/75 = 0.400000 |
| hard | `model-extraction-relu-logits` | 25/80 = 0.312500 |
| hard | `protein-assembly` | 21/78 = 0.269231 |
| hard | `make-doom-for-mips` | 2/80 = 0.025000 |

Seven tasks replace the `5feb120` selection. The retained tasks are `llm-inference-batching-scheduler`, `schemelike-metacircular-eval`, and `torch-pipeline-parallelism`.

## Unchanged matched method and budget

Pi stays at 0.84.2. Native ThinHarness stays at 0.7.0 and commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`. The prompt, native tool schemas, direct OpenAI `gpt-5.6-sol` identity, xhigh reasoning, low verbosity, timeout behavior, one attempt, concurrency one, zero retries, Pi-then-Thin order, checkpoint rules, and stop rules do not change.

The planning cap stays USD 3.00 per cell and USD 60.00 for 20 cells. Official selection evidence does not justify a model-budget correction. Descriptive resource metadata shows larger container requirements, but container resources are not model spend and did not affect selection.

`configs/direct-openai-additional-10-runner-spec.json` remains a launch-disabled specification. No paid launcher exists. `scripts/direct-openai-additional-10-checks.sh` performs only static, deterministic, package, secret, boundary, and immutability checks.
