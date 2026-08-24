# Paid native ThinHarness E2E provenance

These files are immutable useful receipts copied from the one verifier-passing implementation run. They are not runnable inputs.

Source job: `jobs/native-thinharness-paid-regex-log-20260824-054754-4cbc4e1a`

Source trial: `regex-log__NRLsaz4`

Reproduction repository commit used for the run: `aeb3ebad41e993633d6fb6463bc155edbacff0e7`

| Durable file | Source |
| --- | --- |
| `api-budget.json` | `regex-log__NRLsaz4/agent/api-budget.json` |
| `container-preflight.json` | `regex-log__NRLsaz4/agent/container-preflight.json` |
| `corrected-accounting-reconciliation.json` | Derived after review from the immutable raw token classes and preserved prices |
| `host-agent-setup.json` | `regex-log__NRLsaz4/agent/host-agent-setup.json` |
| `native-thinharness-result.json` | `regex-log__NRLsaz4/agent/native-thinharness-result.json` |
| `harbor-config.json` | job `config.json` |
| `harbor-lock.json` | job `lock.json` |
| `job-result.json` | job `result.json` |
| `trial-lock.json` | `regex-log__NRLsaz4/lock.json` |
| `trial-result.json` | `regex-log__NRLsaz4/result.json` |
| `verifier-ctrf.json` | `regex-log__NRLsaz4/verifier/ctrf.json` |
| `verifier-reward.txt` | `regex-log__NRLsaz4/verifier/reward.txt` |
| `implementation-budget.json` | `runs/implementation-budget.json` |
| `launch.json` | `runs/paid-20260824-054754-4cbc4e1a.json` |

`api-budget.json`, `native-thinharness-result.json`, and all other source receipts remain byte-for-byte copies of the paid run. The original ledger recorded USD 0.096848 and omitted cache-write pricing. `corrected-accounting-reconciliation.json` does not modify or relabel that ledger; it independently prices the raw cache-write tokens at USD 6.25/million and records the corrected total USD 0.12674175.

`SHA256SUMS.json` records the SHA-256 digest of every durable file above and this provenance file. Job logs, trial logs, verifier installation output, and other transient verbose logs are intentionally excluded. No credential values are present.
