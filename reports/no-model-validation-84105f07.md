# ThinHarness 84105f07 no-model validation

## Result

The checked Harbor/Docker preflight passed with zero model calls. Harbor then ran the `regex-log` verifier and returned the expected reward `0.0` because the agent intentionally did not solve the task.

## Native in-container identity

- ThinHarness commit: `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`
- Source mode for this unpublished-candidate check: explicit transient local git bundle
- Source bundle SHA-256: `fde7f901dd2005e1f0b59e4b53b419bd179b650d858b60464eae77b4b97822fb`
- Wheel SHA-256: `ef76fbd8d4e61d5f117498d17cc6102ee68af40ce3bc8862877f9ce218364b4c`
- Execution: Harbor task container, `/app`, Ubuntu 24.04 x86_64, Python 3.12.3
- Native plugins: `BashPlugin` and `FilesystemPlugin`
- Native tools: `bash`, `read`, `edit`, `write`
- Prompt SHA-256: `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`

Canonical GitHub remains the durable source default. The local checkout path is not stored in configuration. The host bundle, in-container bundle, and in-container source checkout were removed after the exact SHA check and wheel build. No bundle or ThinHarness source is committed.

## Controlled native Bash overflow

The preflight invoked the native `bash` tool directly, with no model request, and produced 131,072 deterministic stdout bytes.

- Full SHA-256: `a2706a20394e48179a86c71e82c360c2960d3652340f9b9fdb355a42e3ac7691`
- Model-facing result: 40,258 bytes
- Retained output bytes: 40,000
- Omitted output bytes: 91,072
- Artifact root: contained relative path under `/app/.thinharness/outputs/`
- Native Bash retrieval: independently returned exact size and SHA-256
- Durable host copy: `artifacts/no-model-preflight-84105f07/bash-overflow-full.bin`
- Container artifact removed before verifier handoff: yes

The credential sentinel remained absent from native Bash inheritance. The model-loop parent was non-dumpable, lacked `CAP_SYS_PTRACE`, and denied `/proc/<parent>/environ` access.

## Durable evidence

- `artifacts/no-model-preflight-84105f07/SUMMARY.json`
- `artifacts/no-model-preflight-84105f07/SHA256SUMS.json`
- `artifacts/no-model-preflight-84105f07/container-preflight.json`
- `artifacts/no-model-preflight-84105f07/bash-overflow-full.bin`
- `artifacts/no-model-preflight-84105f07/host-agent-setup.json`
- Harbor job, trial, launch, lock, and verifier receipts in the same directory
