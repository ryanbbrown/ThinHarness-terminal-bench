# ThinHarness Terminal-Bench

This repository reproduces one ThinHarness run on Terminal-Bench 2.1. It owns Harbor configuration, launch controls, the frozen prompt, budget accounting, tests, receipts, and reports. It does not contain ThinHarness product code.

## Frozen identity

- Harbor: `0.21.0`
- Dataset: `terminal-bench/terminal-bench-2-1@sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`
- Task: `terminal-bench/regex-log`
- ThinHarness: candidate commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`
- Model: direct OpenAI Responses API, `gpt-5.6-sol`, xhigh reasoning, low text verbosity
- Prompt SHA-256: `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`
- Attempts and concurrency: 1
- Harbor, provider, output, and tool retries: 0
- Spend caps: USD 0.50 per attempt and USD 1.00 across implementation runs

## Architecture

`NativeThinHarnessAgent` runs on the host only because Harbor needs an agent object. It creates a staging directory, uploads this repository's runner controls, starts setup and run processes, and copies receipts. It does not import ThinHarness and does not define model-facing tools.

The setup process runs inside the task container. By default it clones canonical GitHub at the exact commit. For an explicitly authorized unpublished candidate, `TB_THINHARNESS_LOCAL_SOURCE` creates one self-cleaning exact-HEAD git bundle, stages it into Harbor, and removes both host and container bundle staging after the in-container SHA check. The repository never stores the bundle, source checkout, or local path. Both source modes build the wheel inside the task container, hash it, install it in an isolated environment, and record package and source identity.

The model loop also runs there. It uses ThinHarness `BashPlugin` and `FilesystemPlugin` with frozen complete native `bash`, `read`, `edit`, and `write` schemas rooted at `/app`. The controlled no-model preflight forces native Bash past its output bound, verifies the bounded model-facing result, downloads the complete `.thinharness/outputs` artifact to durable Harbor logs, checks exact bytes and SHA-256, and removes the container artifact before verifier handoff. The credential enters through a short-lived anonymous descriptor, not the model-loop environment. Before native tools run, the Linux parent becomes non-dumpable and verifies that `CAP_SYS_PTRACE` is absent.

The agent writes the API ledger and result under `/logs/agent`, Harbor's durable agent-log mount. Harbor receives control only after the in-container process ends and then runs the task verifier against the same `/app` workspace.

## Validate without a model

Prerequisites: Docker and `uv`. Do not set `OPENAI_API_KEY` for these commands.

```bash
./scripts/no-model-checks.sh
./scripts/container-preflight.sh

# Explicit temporary override only while the pinned commit is not on canonical GitHub:
TB_THINHARNESS_LOCAL_SOURCE=/path/to/clean/thinharness ./scripts/container-preflight.sh
```

The first command runs behavior tests, lint, types, boundary checks, and secret scans. The second runs the actual Harbor staging path on `regex-log`. It builds and installs the pinned wheel, inspects native tool schemas, proves native Bash overflow artifact behavior and credential isolation, makes zero model calls, returns to Harbor, and lets Harbor invoke the verifier. The unsolved preflight task is expected to get verifier reward 0; its purpose is to prove the handoff without spend.

## Run the one paid task

Put `OPENAI_API_KEY` in the process environment through a secure shell or secret manager. Do not create a dotenv file. Then run:

```bash
./scripts/run-paid.sh

# Use the same explicit temporary override only while canonical GitHub lacks the pin:
TB_THINHARNESS_LOCAL_SOURCE=/path/to/clean/thinharness ./scripts/run-paid.sh
```

The launcher writes a fail-closed prelaunch state before Harbor starts. Each request reserves the maximum affordable direct-API cost before network access. It settles only after exact model identity and complete token details are present. A network failure, missing usage, identity mismatch, interruption, or corrupt ledger leaves the attempt blocked. No wrapper retries occur.

After Harbor exits, validate the single job directory:

```bash
uv run python -m tbench.validate paid jobs/<job-name> --report reports/implementation-e2e-84105f07.json
```

A valid result requires reward `1.0`, exact response identity, a completed ledger, every request receipt, all token classes, the pinned wheel and commit, container identity, and both spend caps.

The prior `758fcf30` E2E result remains immutable in `artifacts/paid-e2e/` and `reports/implementation-e2e.json`: reward 1.0 and corrected USD 0.12674175 API-equivalent spend. It is included in the USD 1.00 cumulative cap. The one newly authorized `84105f07` result belongs in `artifacts/paid-e2e-84105f07/` and `reports/implementation-e2e-84105f07.json`; the launcher refuses a duplicate attempt for that commit.

## Evidence boundary

`evidence/preserved-direct-api-regex-log/` contains immutable historical receipts used to select the cheapest preserved valid task. `evidence/migration-manifest.json` lists every migrated item and every superseded path. The old `adapter.py` host loop and its custom bash/read/edit/write ToolSpecs were not copied. Historical JSON may describe that old run, but it is inert and never imported.

No command in this repository uploads, publishes, pushes, creates a remote, or runs a broader pilot.
