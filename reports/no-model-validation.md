# No-model validation

Final validation date: 2026-08-24 UTC.

## Static and behavior checks

`./scripts/no-model-checks.sh` passed:

- pytest: 32 passed
- Ruff: passed
- Pyright: 0 errors, 0 warnings
- repository/product boundary and secret scan: passed

The tests exercise durable request reservation and settlement, missing usage, wrong model identity, cap carryover, ledger corruption, exact Harbor launch limits, the stage-only host agent, prompt and historical receipt hashes, forbidden adapter paths, and independent receipt validation.

## Harbor container preflight

Command: `./scripts/container-preflight.sh`

Final job: `jobs/native-thinharness-preflight-regex-log-20260824-070642-6e4ced70`

Durable copy: `artifacts/no-model-preflight/`

Results:

- Harbor exit: success, no trial exception
- Model calls: 0
- ThinHarness commit: `758fcf305e468138b03723760d477444592b1916`
- Installed ThinHarness version: `0.7.0`
- Wheel SHA-256: `6b3f03f3ea6cec84e9f8a1e1b716e45f16e86bd95e56e1e8da79e9e30f060a3f`
- Process location: Harbor task container, Ubuntu 24.04 x86_64
- Process cwd and harness root: `/app`
- Native plugins: `bash` and `filesystem`
- Native tools: `bash`, `read`, `edit`, `write`
- Complete schema SHA-256: `bash` `6c5839686662a1a960f70d99800765b8e75823c09e69abf5fed5c595272467c4`, `read` `4bf95fa07a05e1244e996d8d8ead30082ecd148051785b4609826752c9c47b39`, `edit` `e60622ad6b3d61e87b4119972e1eda33ab08bc88f95d803608c8ec986a8c5a3e`, `write` `fbb2cc1304de524a51fc0d7168f82c5200060d739f6a085d253fb03bb7e6b1ef`
- Linux model-loop dumpable flag: 0
- Effective `CAP_SYS_PTRACE`: absent
- Native Bash sentinel in own environment: absent
- Native Bash access to `/proc/<parent>/environ`: blocked with permission denied
- Direct provider URL: `https://api.openai.com/v1`
- Model settings: `gpt-5.6-sol`, xhigh reasoning with automatic summary, low text verbosity
- Provider/output/tool retries: 0/0/0
- Prompt SHA-256: `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`
- Harbor verifier: invoked after the agent returned against the shared workspace
- Verifier reward: 0.0, expected because no model solved the task

`artifacts/no-model-preflight/container-preflight.json` contains complete native schemas and hashes, plugin origins, a no-network OpenAI payload probe, staged control hashes, credential-isolation evidence, wheel provenance, package versions, roots, and environment identity. The trial receipt proves Harbor executed the verifier after the stage-only agent returned.

## Paid validation

The later authorized paid `regex-log` attempt passed with verifier reward 1.0. Its immutable source ledger remains byte-for-byte unchanged and records USD 0.096848. `artifacts/paid-e2e/corrected-accounting-reconciliation.json` independently prices raw cache-write tokens at USD 6.25/million, producing the corrected USD 0.12674175 total. The durable report is `reports/implementation-e2e.json`. No second paid task was run.
