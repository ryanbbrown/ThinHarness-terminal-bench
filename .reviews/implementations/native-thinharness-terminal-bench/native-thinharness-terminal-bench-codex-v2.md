## Verdict: changes requested

## Findings

1. High — Cache-write tokens are priced as free. `tbench/container_runner.py:280` removes `cache_write_tokens` from ordinary input, and `tbench/budget.py:234-238` does not price them. The preserved receipt proves that cache-write tokens use the ordinary input rate. The paid run has 4,783 cache-write tokens, so its API-equivalent cost is USD 0.120763, not USD 0.096848. This also lets later requests spend more than the ledger permits. Update the ledger, validator, report, and receipt hashes. A new paid run is not needed.

2. High — The committed paid spend is not part of future budget checks. `tbench/launch.py:101-102` starts at zero when `runs/implementation-budget.json` is absent, and `.gitignore:6` excludes that state. Therefore, a fresh checkout ignores the paid attempt in `artifacts/paid-e2e/implementation-budget.json`. Later runs can exceed the USD 1.00 implementation cap.

3. High — Model-facing Bash can access the API key through the runner process. `tbench/agent.py:137-142` starts the runner with `OPENAI_API_KEY`; `tbench/container_runner.py:359-375` keeps it in the environment while Bash runs as the same root user. `inherit_env=False` stops normal inheritance, but it does not prevent access through `/proc/<parent-pid>/environ` on a permissive container. Isolate the credential process or block `/proc` and ptrace access before model tools start.

4. High — Chained requests can be under-reserved. `tbench/container_runner.py:297` carries only the prior response’s input tokens. The next Responses request also includes the prior output as context. The fixed 10,000-token cushion is smaller than the authorized 13,753-token first output shown in `artifacts/paid-e2e/api-budget.json:13`. A long response can therefore make the next request exceed its reservation before settlement detects the breach.

5. Medium — Paid-launch authorization has a race. `tbench/launch.py:132-143` reads the state and then replaces it without an exclusive lock. Two launcher processes can both see an available budget and start separate Harbor jobs. Harbor concurrency limits apply only inside each job.

6. Medium — The artifact validator does not independently calculate request cost. `tbench/validate.py:266-278` only sums the recorded request costs. A consistently underpriced ledger passes validation, which is why finding 1 was not detected.

## Missing or follow-up tests

- Price nonzero cache-write tokens and assert the corrected USD 0.120763 total.
- Make the validator reject a coherent but underpriced ledger.
- Simulate a chained response with more than 10,000 output tokens.
- Test a fresh checkout with committed paid spend.
- Start two mocked paid launchers concurrently and prove only one can proceed.
- Use a sentinel credential and prove native Bash cannot read it from its environment or `/proc`.
- Run the full no-model test, lint, type, secret-scan, and artifact-validation suite after the fixes. Do not repeat the paid attempt only to correct accounting.

## Open questions

None.