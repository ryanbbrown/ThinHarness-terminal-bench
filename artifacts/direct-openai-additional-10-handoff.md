# Additional ten-task direct benchmark handoff

Status: fail-closed at the per-cell cap. Nineteen cells were consumed. Seventeen completed normally, one ended in a non-credit `cyber_policy` refusal without a verifier, and `make-doom-for-mips--pi` ended `cap_exceeded` with verifier reward 0. `make-doom-for-mips--thinharness` was not run.

The verifier score is 15 over 18 outcomes. Pi scored 8 over 10 outcomes; ThinHarness scored 7 over 8 outcomes. The run used 298 upstream requests, 435 native tool calls, and USD 16.89269325 API-equivalent spend. Actual cash is unavailable.

The cap cell used 41 successful upstream requests but recorded 42 native attempts. Attempt 42 was denied locally before an upstream marker. Cell spend was USD 3.02611250, which exceeded the USD 3.00 cap by USD 0.02611250. The durable budget block remains set.

Machine report: [`reports/direct-openai-additional-10-pairwise.json`](../reports/direct-openai-additional-10-pairwise.json). Cap receipt: [`artifacts/direct-openai-additional-10-pairwise/CAP_STOP.json`](direct-openai-additional-10-pairwise/CAP_STOP.json). Full evidence: [`artifacts/direct-openai-additional-10-pairwise/`](direct-openai-additional-10-pairwise/). Reproduce with `uv run python -m tbench.direct_additional_finalize check`.

The report includes exact cell outcomes, harness and empirical-stratum totals, eight paired results with two verifier outcomes, all failures, identities, hashes, traces, the recovery receipt, and the separate historical four-task post-fix sample. Do not generalize this incomplete matched campaign.
