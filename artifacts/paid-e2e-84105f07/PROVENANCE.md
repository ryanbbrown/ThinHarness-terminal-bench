# Paid native ThinHarness 84105f07 E2E provenance

These files are immutable useful receipts copied from the one verifier-passing integration run. They are not runnable inputs.

Source job: `jobs/native-thinharness-paid-84105f07-regex-log-20260824-181350-7896027a`

Source trial: `regex-log__P2whFDd`

Reproduction repository commit used for the run: `a11dffd639902c558dbdd05a9610db8214da4761`

ThinHarness commit built and installed in the task container: `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`

Transient source bundle SHA-256: `5b1b53ee96796ee50a13fb22f01a0f922927ca322fd2db1cf173b8cf8c05d0a2`

Installed wheel SHA-256: `1954f0edbea2b4fc340f93d1eacade72cd5cd9b9fa709b76683e978a57ae1a16`

| Durable file | Source |
| --- | --- |
| `api-budget.json` | `regex-log__P2whFDd/agent/api-budget.json` |
| `bash-overflow-full.bin` | `regex-log__P2whFDd/agent/bash-overflow-full.bin` |
| `container-preflight.json` | `regex-log__P2whFDd/agent/container-preflight.json` |
| `corrected-accounting-reconciliation.json` | Independently derived from the immutable raw token classes and recorded prices |
| `host-agent-setup.json` | `regex-log__P2whFDd/agent/host-agent-setup.json` |
| `native-thinharness-result.json` | `regex-log__P2whFDd/agent/native-thinharness-result.json` |
| `harbor-config.json` | job `config.json` |
| `harbor-lock.json` | job `lock.json` |
| `job-result.json` | job `result.json` |
| `trial-lock.json` | `regex-log__P2whFDd/lock.json` |
| `trial-result.json` | `regex-log__P2whFDd/result.json` |
| `verifier-ctrf.json` | `regex-log__P2whFDd/verifier/ctrf.json` |
| `verifier-reward.txt` | `regex-log__P2whFDd/verifier/reward.txt` |
| `implementation-budget.json` | `runs/implementation-budget.json` after Harbor exit |
| `launch.json` | `runs/paid-20260824-181350-7896027a.json` |

The source receipts are byte-for-byte copies. `corrected-accounting-reconciliation.json` independently confirms the recorded request costs from the raw ordinary, cached, cache-write, output, and reasoning token classes. The attempt API-equivalent cost is USD 0.10979125. With the prior corrected USD 0.12674175 result, cumulative implementation spend is USD 0.236533. Actual cash cost was not reported.

The transient bundle is not preserved because it contains ThinHarness product source. The launch, Harbor, setup, preflight, and agent receipts preserve its exact hash and prove the exact in-container commit and wheel. The setup receipt proves removal of the container bundle and native Bash overflow artifact. The host temporary bundle path no longer exists.

`SHA256SUMS.json` records the SHA-256 digest of every durable file above and this provenance file. Job logs, trial logs, verifier installation output, and other transient verbose logs are intentionally excluded. No credential values are present.
