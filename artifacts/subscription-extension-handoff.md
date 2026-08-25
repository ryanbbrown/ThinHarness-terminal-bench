# Three-pair Codex-subscription extension handoff

Status: the authorized run completed exactly six real cells with no reruns. Pi passed 2/3 tasks; ThinHarness passed 1/3. The authoritative report is `reports/codex-subscription-3task-extension.json`; its durable copy and hash manifest are `artifacts/codex-subscription-3task-extension/SUMMARY.json` and `SHA256SUMS.json`. Subscription cash cost is unavailable. API-equivalent values use the frozen direct-API schedule and are not cash cost.

## Freshness and no-model gate

The frozen tasks are `configure-git-webserver`, `pytorch-model-recovery`, and `constraints-scheduling`. All have a 15-minute expert estimate and 2048 MiB memory. They were the first three eligible tasks after excluding every prior paid or attempted task and sorting the minimum remaining tier by memory, agent timeout, compressed amd64 image bytes, and task name. Their task TOML SHA-256 values are `ebb40d72f689512cbd90d865d88ef966b6665ab215544f9247b898b7fa94751b`, `851a51204f53482a31f47cdf8833128cf421113b0331011286940fc857c37dfd`, and `7b9842de16d74e8faf8c7c0aa03b0b81145941cb12dd322d81ae23fc48607250`. Their amd64 image digests are `sha256:9e48389b917fd4650dda1f64406bd7198bbf20dc1c6b0e5c4d81a3c16369f88c`, `sha256:63c804250786f1450028e68f66efac1b0ab58718e6bc98686e62f3cd72b0f395`, and `sha256:567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0`.

Before selection was added, all three names were absent from current and preserved benchmark content and Git refs, `/Users/ryanbrown/code`, and `/Users/ryanbrown/.bb/worktrees`. The preserved experiment path was absent. The launcher then found no selected real cell or real job before preflight or real launch. `configs/subscription-extension-selection.json` freezes this proof and all earlier conservative exclusions.

The first zero-upstream gate exposed that Pi parsed the leading `-` in the PyTorch instruction as a CLI option. A supported argument-boundary correction was required; Pi 0.84.2 rejected a standalone `--`, so the final runner prefixes a newline only when a task instruction begins with `-`. Both failed preflights are preserved with hashes and prove zero model, subscription, or upstream requests. The final six-cell preflight passed: every cell made two controlled fake requests, executed one native Bash call, reached its verifier with expected reward zero, and used zero subscription requests. The real launcher validated that finalized hash manifest and summary before it started.

## Per-cell results

All times are seconds. Usage columns are ordinary / cached / cache-write / output / reasoning tokens. Cost is API-equivalent USD.

| cell | reward | requests | tools | batching: tool-bearing / multi / max | wall / agent / agent phase / verifier | usage | cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| `configure-git-webserver--pi` | 1 | 16 | 22 | 15 / 5 / 3 | 366.600903 / 272.261083 / 273.895625 / 13.136117 | 48965 / 139776 / 0 / 11645 / 7736 | 0.664063 |
| `configure-git-webserver--thinharness` | 0 | 10 | 12 | 9 / 3 / 2 | 270.987330 / 175.455613 / 176.250737 / 14.985433 | 28001 / 34816 / 0 / 6728 / 3915 | 0.359253 |
| `pytorch-model-recovery--pi` | 0 | 18 | 19 | 17 / 2 / 2 | 254.304440 / 217.874579 / 218.784647 / 8.159465 | 45166 / 158208 / 0 / 9509 / 4638 | 0.590204 |
| `pytorch-model-recovery--thinharness` | 0 | 13 | 13 | 12 / 1 / 2 | 245.386843 / 190.978771 / 191.815451 / 20.184597 | 24222 / 96256 / 0 / 7669 / 3792 | 0.399308 |
| `constraints-scheduling--pi` | 1 | 4 | 7 | 3 / 2 / 4 | 166.374287 / 40.616971 / 42.373853 / 15.718308 | 7044 / 7680 / 0 / 1867 / 1254 | 0.095070 |
| `constraints-scheduling--thinharness` | 1 | 6 | 8 | 5 / 1 / 4 | 181.016652 / 45.346185 / 48.015814 / 20.039904 | 12128 / 16384 / 0 / 2052 / 1027 | 0.130392 |

Pi tool counts by cell were `bash` 17 / `write` 4 / `edit` 1; `bash` 15 / `write` 3 / `edit` 1; and `read` 4 / `bash` 2 / `write` 1. ThinHarness counts were `bash` 12; `bash` 10 / `write` 2 / `edit` 1; and `read` 3 / `bash` 4 / `write` 1. Exact arguments, request payload sizes, per-request usage and duration, and full response traces remain in the report and cell artifacts.

## Pair and aggregate comparison

For `configure-git-webserver`, Pi minus ThinHarness was +1 reward, +6 requests, +10 tools, +95.613573 wall seconds, +125924 input tokens, and +USD 0.304810 API-equivalent cost. For `pytorch-model-recovery`, both failed; Pi minus ThinHarness was +5 requests, +6 tools, +8.917597 wall seconds, +82896 input tokens, and +USD 0.190896. For `constraints-scheduling`, both passed; Pi minus ThinHarness was -2 requests, -1 tool, -14.642365 wall seconds, -13788 input tokens, and -USD 0.035322.

Across the three extension tasks, Pi totaled reward 2, 38 requests, 48 tools, 787.279630 wall seconds, 101175 ordinary input, 305664 cached input, 0 cache-write, 23021 output, 13628 reasoning tokens, and USD 1.349337 API-equivalent cost. ThinHarness totaled reward 1, 29 requests, 33 tools, 697.390825 wall seconds, 64351 ordinary input, 147456 cached input, 0 cache-write, 16449 output, 8734 reasoning tokens, and USD 0.888953. Pi minus ThinHarness was +1 pass, +9 requests, +15 tools, +89.888805 wall seconds, +195032 total input tokens, and +USD 0.460384.

Adding the matched post-fix `crack-7z-hash` pair gives the complete four-task post-fix sample. Pi totaled 3/4 passes, 53 requests, 77 tools, 1913.611837 wall seconds, and USD 1.664707 API-equivalent cost. ThinHarness totaled 2/4 passes, 52 requests, 59 tools, 1788.606700 wall seconds, and USD 1.395958. These are descriptive results for only four tasks, not a general harness ranking.

## Trace causes

- `configure-git-webserver`: Pi created the explicit `user` account, installed SSH and nginx, configured `/git/server`, tested an SSH clone/push, and left a working push-to-web deployment. ThinHarness chose the pre-existing `ubuntu` account even though the requested clone identity was `user@server`. Its own smoke used local `runuser -u ubuntu`; the verifier later attempted `user@localhost`, could not complete the clone/push path, and received HTTP 404. The verifier trace records the 404. The failure is a trajectory choice, not an infrastructure error.
- `pytorch-model-recovery`: both trajectories produced a valid TorchScript file, preserved `weights.pt`, matched all non-output state keys, and passed four of five verifier tests. Both independently reconstructed an 8-head, batch-first, one-input model and scripted `forward(src)`. The verifier's recovered architecture uses 4 heads, sequence-first layers, and `forward(src, tgt)`. Both failed only when the verifier called the scripted model with two tensors: `forward() expected at most 2 argument(s) but received 3`. Both traces show local checks that called only `model(src)`, so neither tested the required two-input signature.
- `constraints-scheduling`: both read all three calendars, selected the same earliest valid 2024-01-17 11:00–12:00 UTC slot, wrote one three-attendee ICS event, and passed all three verifier checks. Pi completed 7 tools in 3 tool-bearing responses, while ThinHarness completed 8 tools in 5 tool-bearing responses; this batching difference explains ThinHarness's two additional requests.

Every real response identified `gpt-5.6-sol` and included exact cached and cache-write fields. Both harnesses retained xhigh reasoning, low verbosity, native tools at `/app`, sequential ThinHarness tool execution, zero retries, cproxy `ef96cba`, and the 1800-second owned ThinHarness provider transport. The real run used runner Git head `1f24cb48fa972702d299b0d27a3cc8cd63462394` with source identity `854a6ff8380f966de4ae5a7c2b4d6ea6ebee5e55f599f0e8c6d299719339f300` and transient bundle SHA-256 `ed31eb0b3310b0524dd922c1774745e393eb2c7b4a568cdb7f52510490286050`.
