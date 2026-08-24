## Verdict: changes requested

The frozen diff implements the plan faithfully: stage-and-launch host agent, pinned in-container wheel build, native `BashPlugin`/`FilesystemPlugin` rooted at `/app`, fail-closed budget ledger, direct-OpenAI identity checks, frozen prompt hash, zero retries, and durable receipts. I reconciled the committed `paid-e2e` artifacts by hand (token totals, per-request costs, cap math, ledger reconciliation, verifier reward) and they are internally consistent. The issues below are test-coverage gaps for required fail-closed behavior, not confirmed code defects.

## Findings

### 1. Missing test: cap-breach-on-settle fail-closed path is untested (medium)
`tbench/budget.py:228-237` — `settle_request` has three breach branches (`cost > reservation`, `spent > attempt_ceiling`, `prior + spent > implementation_ceiling`) that set `fatal_error`, `status="failed"`, and re-raise. This is the core spend-control guarantee the plan calls out ("cap each attempt at USD 0.50 and all implementation attempts at USD 1.00 ... reject ... when ... over cap"). No test in `tests/test_budget.py` exercises any of these branches. The existing tests cover missing-usage and wrong-identity failures, but not overspend. Add a test that settles a request whose `output_tokens` make `api_equivalent_cost_usd` exceed `reserved_usd` and asserts the ledger becomes `failed` with `fatal_error` set, `spent_usd` recorded, and a second `reserve_request` is rejected.

### 2. Missing test: `initialize_ledger` refuses to overwrite an existing ledger (low)
`tbench/budget.py:30-32` raises `BudgetError` if `path.exists()`. This durability guard (no silent replacement of prior evidence) is untested. Add a test that calls `initialize_ledger` twice on the same path and asserts the second raises.

### 3. Missing test: `finalize_ledger` rejects finalization with an in-flight request (low)
`tbench/budget.py:262-264` raises if `in_flight_request_id` is not None. Untested. Add a test that reserves, then calls `finalize_ledger` without settling, and asserts it raises and leaves the reservation intact.

### 4. Missing test: `load_ledger` corruption/duplicate-id/version rejection (low)
`tbench/budget.py` rejects invalid `version`, duplicate `request_id`, and orphaned reservations. Only the orphaned-reservation case is tested (`test_corruption_and_orphaned_reservations_are_rejected`). Add cases for a wrong `version` and a duplicate `request_id`.

### 5. Missing test: launch refuses when prior launch is unsettled (low)
`tbench/launch.py:84-86` (`_load_prior_state`) refuses a new paid launch when prior state is `status == "launched"`. `tests/test_launch_contract.py` only checks the `harbor_command` vector. Add a test that writes an `implementation-budget.json` with `status: "launched"` and asserts `run("paid")` raises before invoking Harbor.

## Missing or follow-up tests the writer should run
- The five tests above (no model calls).
- Re-run `./scripts/no-model-checks.sh` after adding them to confirm 13 → ~18 passing and pyright/ruff stay clean.
- Optionally, a container-side unit test for `BudgetedDirectOpenAIProvider.create_response` using a fake `OpenAIProvider` base to prove a network failure after `reserve_request` leaves the reservation unresolved and the ledger fail-closed. This requires importing `thinharness`, so it belongs behind the container venv or a dev extra, not the host no-model suite.

## Residual risks / open questions
- **Wheel build is not byte-reproducible.** The no-model preflight wheel SHA-256 (`d3793cda...`, `reports/no-model-validation.md:30`) differs from the paid wheel SHA-256 (`a8c6c176...`, `reports/implementation-e2e.json:50`), both built from the same pinned commit `758fcf3`. Each receipt validates its own wheel hash internally, and the commit pin is the real anchor, but a rebuild will produce a different hash. The plan records "wheel hash" per-run, so this is acceptable; flagging so reviewers do not treat the wheel hash as a canonical pin.
- **`_PAID_RUN_REPOSITORY_COMMIT` is hardcoded** to `aeb3ebad...` (`tbench/validate.py:38`). The current snapshot is `2c0bf4a`, which only added artifacts/validator/tests and did not touch the staged control files, so `validate_container_preflight` still passes. If staged control files ever change, `validate_container_preflight` will catch the mismatch — good — but the `reproduction_repository_commit` field is not checked against `git`, so it can go stale silently.
- **Manual recovery after a crashed paid launch.** `launch.py` leaves `implementation-budget.json` as `status: "launched"` if Harbor or the ledger settlement fails, correctly blocking the next launch. There is no automated recovery path; a human must inspect and reset the state. This matches the plan's "reject when incomplete," but worth documenting in the README.
- No confirmed correctness bugs or regressions found in the feature diff.
