# Codex-subscription matched smoke handoff

Status: no-model gate passed; no subscription-backed model request has been made.

## Selected tasks

The exact four matched tasks are:

1. `raman-fitting`
2. `fix-git`
3. `prove-plus-comm`
4. `crack-7z-hash`

All are in Terminal-Bench 2.1's minimum five-minute expert-time tier. The deterministic rule, image identities, resource bounds, task TOML hashes, and eight-cell order are frozen in `configs/subscription-smoke-selection.json`.

Conservatively excluded prior paid or launched tasks: `build-pmars`, `extract-elf`, `fix-code-vulnerability`, `hf-model-inference`, `kv-store-grpc`, `overfull-hbox`, `regex-log`, `reshard-c4-data`, and `write-compressor`. The previously preserved ignored experiment path was checked and no longer exists. Existing repository receipts and the conservative historical exclusion list were used; selected tasks do not overlap it.

## Backend proof

- Route: per-cell authenticated gateway -> cproxy `0.1.0` at `ef96cbaea614753171627c059297e163fed0bc53` -> `https://chatgpt.com/backend-api/codex/responses`.
- Authentication: Ryan's host Codex CLI reports `Logged in using ChatGPT`. cproxy successfully validated the host OAuth file. OAuth was not copied into either task container.
- The real backend preflight started the exact cproxy route, validated OAuth, made zero subscription requests, and made zero upstream network requests.
- The controlled gateway contract accepted ThinHarness non-streaming Responses JSON and Pi streaming Responses SSE, returned exact `gpt-5.6-sol` identity, and supplied input, cached input, cache-write, output, and reasoning usage.
- The gateway rejects an absent or wrong random per-cell bearer, records every sanitized request and complete response, and stops after each cell. No bearer is committed.
- Direct OpenAI and Doppler credentials are rejected before launch.

## Native in-container proof

Two real Harbor/Docker `fix-git` preflight trials ran with no subscription call:

- Pi `0.84.2`, Node `22.23.1`, package-lock SHA-256 `0f34d01dda1837fd634d0562d2c0350ff982da133de59f36fccdac62835fc1c0`.
- ThinHarness `0.7.0`, exact commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`, transient bundle SHA-256 `3762a6c9275b884406ededa4207dcacb91cee2ad0dd2b72377bf8d88f46be82b`, in-container wheel SHA-256 `40033931385540a8cdb08a73c4259aa294b66ed74821f89ed70c37c556548ec9`.
- Both loops executed at `/app` with native `read`, `bash`, `edit`, and `write` tools.
- A controlled fake first response invoked each native Bash tool. Both proved no reusable OAuth or direct API credential exists in the task container. The second fake response ended the loop and handed the workspace to Harbor's verifier.
- Each preflight made two controlled fake requests, one native Bash call, zero real model requests, and got the expected unsolved verifier reward `0.0`.
- ThinHarness source and bundle staging were removed. No bundle or product source is in this repository.

Durable evidence is under `artifacts/codex-subscription-4task-preflight/`. The reproduced summary is `reports/codex-subscription-4task-preflight.json`.

## Matched settings and unavoidable differences

Matched: `gpt-5.6-sol`, xhigh reasoning, summary auto, low text verbosity, frozen prompt hash `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`, task, `/app` root, native tool names, one attempt, concurrency one, and zero retries.

Unavoidable and recorded:

- Pi requires streaming Responses. The gateway re-emits cproxy's complete response as SSE. ThinHarness consumes the same response as non-streaming JSON.
- Native tool schemas and declaration order differ. The gateway preserves both exact schema payloads.
- Pi serializes the same frozen prompt through its native developer/system input; ThinHarness uses native Responses instructions.
- Pi 0.84.2 native Bash inherits the ephemeral gateway bearer from process environment. ThinHarness filters it. The bearer is not OAuth, expires with the one-cell gateway, and every use is audited.
- The subscription backend provides usage, not cash cost. Reports must keep cash cost unavailable and must not estimate API cost.

## Validation

- 48 pytest tests passed.
- Ruff passed.
- Pyright reported zero errors and warnings.
- Repository boundary and secret checks passed.
- Both real Docker preflight trials passed without agent exceptions and reached the verifier.
- The durable artifact validator and SHA-256 manifest passed and reproduced the committed summary.
- Project sdist and wheel built; the wheel contains no `thinharness/` product package.
- The benchmark has no remote, no bundle, and no pushed result. `FIRSTMATE-QUEUE.md` was not edited.

## Safe authorized launch

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  ./scripts/run-subscription-smoke.sh
```

The launcher will run eight cells sequentially and refuse to replace existing durable output. Expected output:

- `artifacts/codex-subscription-4task/cells/<task>--<harness>/`
- `artifacts/codex-subscription-4task/SUMMARY.json`
- `artifacts/codex-subscription-4task/SHA256SUMS.json`
- `reports/codex-subscription-4task.json`

The final report will preserve rewards, complete Harbor timing, request and tool counts, backend token/cache/cache-write/output/reasoning usage, complete gateway request/response traces, native tool traces, versions, commits, logs, and pairwise trace observations. Missing fields remain unavailable rather than inferred.

## Blockers

No pre-spend blocker remains. Residual operational risk: cproxy uses an undocumented ChatGPT Codex backend contract. The launcher stops on the first identity, usage, authentication, protocol, or evidence failure and has no retry path.
