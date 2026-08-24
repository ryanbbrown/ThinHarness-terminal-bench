# Codex-subscription smoke final handoff

Status: `proc_760b` is stopped. The matched comparison is invalid and incomplete. No cell was rerun, the last three cells were not launched, and finalization made no model, Harbor, cproxy, subscription, direct API, or Doppler request.

The authoritative machine-readable report is `reports/codex-subscription-4task.json`. Its durable copy and all partial evidence are under `artifacts/codex-subscription-4task/`. `SUMMARY.json` contains the same report and `SHA256SUMS.json` covers the preserved evidence files.

## Why there is no comparison

The design required eight cells: four tasks on both harnesses. Five cells were attempted. Only two Pi cells reached a verifier. Both ThinHarness attempts failed in the model loop, and the fifth cell failed before its Pi model loop. `prove-plus-comm--thinharness` and both `crack-7z-hash` cells were not launched. No task has completed results from both harnesses. The used tasks cannot be run again, so neither a continuation nor a rerun can restore the frozen matched design. The partial values below are diagnostic evidence, not benchmark results.

## Attempted cells

All times are seconds. Usage comes from complete gateway audits, including a response that the ThinHarness client timed out before receiving. `ordinary` is input minus cached and cache-write tokens.

| cell | outcome / reward | wall / setup / agent phase / verifier | audited requests / runner responses | executed tools | input / ordinary / cached / cache-write / output / reasoning |
|---|---:|---:|---:|---:|---:|
| `raman-fitting--pi` | completed / `0` | 451.733851 / 65.395922 / 363.064997 / 8.043638 | 26 / 26 | 27: bash 17, read 5, write 4, edit 1 | 474691 / 46147 / 428544 / 0 / 15852 / 11245 |
| `raman-fitting--thinharness` | RuntimeError / unavailable | 112.170922 / 87.980229 / 10.641984 / unavailable | 3 / 2 | at least 2: bash, read; complete records unavailable | 4988 / 4988 / 0 / 0 / 501 / 90 |
| `fix-git--pi` | completed / `1` | 194.862775 / 104.430850 / 71.300712 / 6.226438 | 10 / 10 | 25: bash 22, read 3 | 68912 / 19248 / 49664 / 0 / 2833 / 900 |
| `fix-git--thinharness` | RuntimeError / unavailable | 31.055965 / 11.859011 / 6.184046 / unavailable | 1 / 0 | 0 executed; response contained 3 bash calls that the client did not receive | 1254 / 1254 / 0 / 0 / 271 / 52 |
| `prove-plus-comm--pi` | setup RuntimeError / unavailable | 27.734142 / 0.124251 / unavailable / unavailable | 0 / unavailable | 0 | 0 / 0 / 0 / 0 / 0 / 0 |

The first timing field after wall is agent setup. Environment setup and the exact timestamps are in the report. Per-request duration, hashes, streaming shape, model identity, tool calls, and token/cache/reasoning usage are also in the report and raw audits. Cash cost is unavailable for every subscription response and was not estimated.

The `raman-fitting--pi` verifier passed file existence and the G peak. It failed only the 2D offset tolerance: expected `1239.09`, got `1469.812`. The other checked 2D values passed. `fix-git--pi` passed both verifier tests.

## Root causes proven by evidence

1. **Both ThinHarness failures used an unintended five-second HTTP timeout.** `tbench/subscription_container.py` creates `httpx.AsyncClient(headers=...)` without a timeout and passes that existing client to `OpenAIProvider`. The provider's separate `timeout=1800` argument does not alter the custom client's five-second default. In `fix-git`, the runner failed after 5.048896 seconds while the gateway completed and audited the response after 7.186541 seconds. In `raman-fitting`, two 2-second responses succeeded; the third took 9.018575 seconds, and the runner failed about five seconds into that request. This explains the blank `provider request failed:` errors and the audit/receipt count differences.

2. **`prove-plus-comm--pi` failed before the agent loop.** Its root `mkdir -p /opt/thinharness-terminal-bench-subscription /logs/agent` setup command returned nonzero. Agent setup lasted 0.124251 seconds; agent execution is null; no audit or receipt exists. The deeper OS reason is unavailable because the launcher discarded that exec result's stdout/stderr and Harbor's configured `--delete` removed the container. No deeper cause is inferred.

3. **Launcher ordering turned the fifth cell failure into the run stop and initially omitted it from durable artifacts.** `_run_cell` requires a nonempty gateway audit before `_archive`. `run()` copies run state and selection to the artifact root only after the full loop. The pre-agent failure therefore produced `gateway audit is empty for prove-plus-comm--pi`, stopped the loop, and skipped normal archival. Finalization copied the preserved job, gateway identity, launch receipt, stopped run state, and selection into the artifact root without executing anything.

## Exact identities and Codex backend evidence

- Benchmark run commit: `fe70ddd7f99fb02857f256b77137364d0a06ea9f`.
- Harbor `0.21.0`; dataset `terminal-bench/terminal-bench-2-1@sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`.
- Model `gpt-5.6-sol`; reasoning `xhigh`, summary `auto`; text verbosity `low`; prompt SHA-256 `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`.
- Pi package `@earendil-works/pi-coding-agent` `0.84.2`; Node `22.23.1`; package-lock SHA-256 `0f34d01dda1837fd634d0562d2c0350ff982da133de59f36fccdac62835fc1c0`.
- ThinHarness `0.7.0` at `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`; transient bundle SHA-256 `cda1f1d8648d7e1e60848ec63326958cdb546f5c4e59ac6ae62340cb52eda710`. The `raman-fitting` receipt records Python 3.13.7 and wheel SHA-256 `8b5312f511664227c88fb40d378756266d0966a05b1c87381874ccf92d63be46`. The `fix-git` receipt records Python 3.13.12 and wheel SHA-256 `83321ed125ca3900059b37ea7a505081475632101dd590554ed82b8dcff824d4`.
- cproxy `0.1.0` at `ef96cbaea614753171627c059297e163fed0bc53`; route `https://chatgpt.com/backend-api/codex/responses`; zero retries.
- All five gateway identities say host Codex OAuth validation succeeded and OAuth was not persisted. The four request-bearing cells preserve 40 successful upstream responses. Every response identifies `gpt-5.6-sol` and has usage. Aggregate audited usage is 549845 input, 478208 cached input, 0 cache-write, 19457 output, and 12287 reasoning tokens. Launch receipts set `direct_openai` false. No bearer or OAuth file is preserved.

## Missing data and blockers

Rewards and verifier data are unavailable for both ThinHarness cells and `prove-plus-comm--pi`. ThinHarness failure receipts have no terminal `RunResult`, aggregate usage, stop reason, or complete executed-tool records. The third `raman-fitting` response's five calls and the first `fix-git` response's three calls were emitted by the backend but not received by the timed-out clients. All execution fields are unavailable for the three unlaunched cells. The setup command's underlying OS error and subscription cash cost are unavailable.

The permanent blocker is the task reuse rule: five selected cells were already attempted, while the eight-cell matched design requires all original cells. The report therefore makes no pairwise or aggregate Pi-versus-ThinHarness claim.
