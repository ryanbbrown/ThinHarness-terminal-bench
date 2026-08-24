# Codex-subscription matched smoke handoff

Status: no-model gate passed; no subscription-backed model request has been made.

## Codex login status correction

Codex CLI `0.147.0` writes `Logged in using ChatGPT` to stderr. The launch script now captures stdout and stderr together, checks the captured value in Bash without a pipe, unsets it before launch, and prints only generic errors. It does not echo Codex status output. A controlled regression emits a private marker and the valid login identity on stderr; the script accepts the identity, does not expose the marker, and reaches two fake `uv` commands without starting Harbor, cproxy, or any model request.

## Prelaunch exact-pin bundle update

The local canonical ThinHarness checkout is clean at later `HEAD` `a2cdebc52e5543e85d0a633b4822f775505fd6ed` and contains the required ancestor `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`. The override no longer requires `HEAD` to equal the pin. It creates a dedicated `refs/heads/thinharness-pin`, bundles that ref only, requires exactly one advertised bundle head, fetches it into an isolated verification repository, verifies its commit, and proves the later source `HEAD` commit is absent.

The zero-request bundle preview against the canonical checkout reported:

- advertised head: `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef refs/heads/thinharness-pin`
- source head excluded: `true`
- upstream requests: `0`
- transient preview bundle SHA-256: `e5742e3fceaadf3e3e8bec6ac1e65a79983ed32e2f9229cc3714ee6b885a9105`
- bundle persisted: `false`

The existing committed Docker preflight evidence and its original bundle/wheel hashes are unchanged. They remain byte-valid evidence for the earlier no-model run. This update did not replace those artifacts.

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

- The original committed gate ran 48 pytest tests. The current exact-pin update runs 49 tests, including clean `HEAD`-ahead regressions for both launch paths.
- Ruff passed.
- Pyright reported zero errors and warnings.
- Repository boundary and secret checks passed.
- Both real Docker preflight trials passed without agent exceptions and reached the verifier.
- The durable artifact validator and SHA-256 manifest passed and reproduced the committed summary.
- Project sdist and wheel built; the wheel contains no `thinharness/` product package.
- The benchmark has no remote, no bundle, and no pushed result. `FIRSTMATE-QUEUE.md` was not edited.

## Safe zero-request preview

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  uv run python -m tbench.subscription_launch bundle-preview
```

This command does not start Harbor, the gateway, cproxy, or any upstream request.

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

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "The launch script captures both Codex login-status streams, recognizes ChatGPT login reported on stderr, removes the captured value, and never displays status details."
    },
    {
      "id": "criterion-2",
      "status": "satisfied",
      "evidence": "A controlled stderr regression proves valid login acceptance, private output suppression, and handoff only to fake uv commands; the full 50-test no-model and static suite passes."
    }
  ],
  "changedFiles": [
    "artifacts/subscription-smoke-handoff.md",
    "scripts/run-subscription-smoke.sh",
    "tests/test_subscription_script.py"
  ],
  "testsAddedOrUpdated": [
    "tests/test_subscription_script.py: models Codex 0.147.0 status on stderr and proves private status details are not exposed"
  ],
  "commandsRun": [
    {
      "command": "uv run --extra dev pytest tests/test_subscription_script.py -q",
      "result": "passed",
      "summary": "The controlled stderr regression passed."
    },
    {
      "command": "./scripts/no-model-checks.sh",
      "result": "passed",
      "summary": "50 tests, Ruff, Pyright, repository boundary, and secret checks passed."
    },
    {
      "command": "bash -n scripts/run-subscription-smoke.sh; git diff --check",
      "result": "passed",
      "summary": "Shell syntax and patch whitespace are valid."
    }
  ],
  "validationOutput": [
    "Controlled Codex status was emitted on stderr and accepted.",
    "The private-status-detail marker was absent from script stdout and stderr.",
    "Only two fake uv commands ran; Harbor and cproxy were not started.",
    "No subscription-backed, direct OpenAI, or Doppler request was made."
  ],
  "residualRisks": [
    "The undocumented ChatGPT Codex backend contract remains an operational risk for the later authorized eight-cell run."
  ],
  "noStagedFiles": true,
  "diffSummary": "Capture Codex login status from both streams without displaying it, then test the stderr behavior with controlled fake executables.",
  "reviewFindings": [
    "parent validation reviewer gate: pending parent orchestration"
  ],
  "manualNotes": "No Harbor process, cproxy request, subscription request, push, remote, or FIRSTMATE-QUEUE.md edit occurred."
}
```
