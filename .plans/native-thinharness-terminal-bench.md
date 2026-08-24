# Native ThinHarness Terminal-Bench reproduction

## Scope

Build a standalone reproduction repository that owns Harbor configuration, launch controls, a frozen Pi prompt, spend controls, tests, receipts, and reports. It must not contain ThinHarness product source. The only preserved source is `/Users/ryanbrown/.bb/worktrees/env_n8eb7j52v2/thinharness/experiments/terminal_bench_2_1`, which is read-only.

## Decisions

- Pin Harbor to `0.21.0`, Terminal-Bench 2.1 to `sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`, ThinHarness to canonical Git commit `758fcf305e468138b03723760d477444592b1916`, GPT-5.6 Sol, direct OpenAI Responses API, xhigh reasoning, low text verbosity, one attempt, concurrency one, and zero Harbor/provider/agent retries.
- Keep only a small host-side Harbor agent. It may stage repository-owned runner and control files and start one process. It must not implement model-facing tools or run the ThinHarness loop on the host.
- In the task container, fetch the canonical ThinHarness commit, build a wheel, install that wheel, and run ThinHarness with its native `BashPlugin` and native filesystem tools. Root all model-facing tools at `/app`. Do not copy ThinHarness product code into this repository.
- Freeze the preserved Pi 0.84.2 system prompt by content and SHA-256. Record the exact prompt hash in preflight and run receipts.
- Implement a durable fail-closed budget ledger. Reserve before each API request, require complete usage and exact response-model identity before settlement, retain unresolved reservations after failures, cap each attempt at USD 0.50 and all implementation attempts at USD 1.00, and reject a new launch when accounting is incomplete or over cap.
- Pass `OPENAI_API_KEY` only through process environment. Never write or print the secret. Ignore local runtime artifacts that can contain transient state.
- Copy only useful immutable evidence from preserved receipts. Add provenance and hashes. Explicitly list the old host-loop proxy adapter as superseded and do not copy it as runnable code.
- Select `terminal-bench/regex-log` for the paid implementation run. Preserved direct-API evidence shows a verifier pass at USD 0.0749275, 35.72584 agent seconds, and 95.837279 wall seconds. It is the lowest-cost preserved valid ThinHarness task; use cost first and wall time second as the selection rule.

## Acceptance checks

- Repository scans find no ThinHarness package/product source and no runnable host-side custom `bash`, `read`, `edit`, or `write` ToolSpecs.
- No-model tests prove exact tool names and schemas, `/app` roots, container process execution, wheel/commit pinning, direct OpenAI URL and model identity checks, xhigh/low wire settings, prompt hash, zero retries, attempt/concurrency limits, budget reservation and failure behavior, durable receipts, and Harbor verifier handoff.
- A container preflight builds and installs the pinned wheel without a model call and records package, wheel hash, commit, tool schema, root, process identity, environment identity, and prompt hash.
- One real `regex-log` attempt uses direct OpenAI, stays within USD 0.50, leaves total implementation-run spend at or below USD 1.00, and gets verifier reward `1.0` before implementation review.
- The paid receipt records actual cash or API-equivalent cost, complete token classes, request count, tool count and names, agent and wall time, result, verifier evidence, exact ThinHarness commit and wheel hash, prompt hash, and environment identity.
- Exactly one successful implementation review-panel cycle runs against the recorded pre-implementation base. Required findings are fixed and validated without another paid attempt unless the fix truly needs it and the total cap permits it.
- Final validation passes, the old worktree is unchanged, no remote exists, and the candidate is committed without push or publication.

## Validation

1. Unit and integration tests with no model calls.
2. Lint and type checks defined by the repository.
3. Secret and forbidden-adapter scans.
4. Docker no-model preflight with the actual Harbor/container staging path.
5. Paid `regex-log` attempt and independent receipt/verifier validator.
6. One implementation review panel, synthesis, required fixes, then repeat all no-model and static checks.
7. Inspect final diff, receipts, reports, repository status, remotes, and the preserved worktree status.
