# No-model validation

Final validation date: 2026-08-24 UTC.

## Static and behavior checks

`./scripts/no-model-checks.sh` passed:

- pytest: 13 passed
- Ruff: passed
- Pyright: 0 errors, 0 warnings
- repository/product boundary and secret scan: passed

The tests exercise durable request reservation and settlement, missing usage, wrong model identity, cap carryover, ledger corruption, exact Harbor launch limits, the stage-only host agent, prompt and historical receipt hashes, forbidden adapter paths, and independent receipt validation.

## Harbor container preflight

Command: `./scripts/container-preflight.sh`

Final job: `jobs/native-thinharness-preflight-regex-log-20260824-054340-1d064a9e`

Durable copy: `artifacts/no-model-preflight/`

Results:

- Harbor exit: success, no trial exception
- Model calls: 0
- ThinHarness commit: `758fcf305e468138b03723760d477444592b1916`
- Installed ThinHarness version: `0.7.0`
- Wheel SHA-256: `d3793cda41342d0ae2808a875bce822f47145cadf20e91db1918f0fb779b68b2`
- Process location: Harbor task container, Ubuntu 24.04 x86_64
- Process cwd and harness root: `/app`
- Native plugins: `bash` and `filesystem`
- Native tools: `bash`, `read`, `edit`, `write`
- Direct provider URL: `https://api.openai.com/v1`
- Model settings: `gpt-5.6-sol`, xhigh reasoning with automatic summary, low text verbosity
- Provider/output/tool retries: 0/0/0
- Prompt SHA-256: `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`
- Harbor verifier: invoked after the agent returned against the shared workspace
- Verifier reward: 0.0, expected because no model solved the task

`artifacts/no-model-preflight/container-preflight.json` contains complete native schemas, plugin origins, a no-network OpenAI payload probe, staged control hashes, wheel provenance, package versions, roots, and environment identity. The trial receipt proves Harbor executed the verifier after the stage-only agent returned.

## Paid validation

No paid attempt was run. The parent explicitly directed this implementation worker not to make paid model calls. A verifier-passing paid receipt is therefore still required before implementation review can start.
