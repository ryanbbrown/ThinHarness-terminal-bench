# Implementation review synthesis v2

## Cycle result

The implementation review cycle succeeded on snapshot `2c0bf4a6b8abe2ac401a2ce6437626fd64b46eb8` against base `62c43c9ba5a0da1b23f2e58f89d4d29527744175`.

Codex and GLM completed. Claude was skipped with the review-panel's supported option after four failed attempts returned HTTP 529 during a confirmed Claude service outage. The failed attempts do not count as review cycles.

## Required fixes

1. Price cache-write tokens at the preserved USD 6.25 per million rate. Recalculate each request and the paid total from raw token receipts. Update the validator, report, ledger evidence, and hashes. The corrected paid total is USD 0.12674175, which stays below both caps.
2. Make the validator calculate each request cost from token classes. It must reject a ledger with internally consistent but incorrect recorded costs.
3. Include committed implementation spend in every fresh-checkout launch decision. Since the committed task passed its verifier, the paid launcher must refuse another implementation task by default.
4. Add one exclusive launch lock that remains held for the full paid Harbor process. A concurrent launcher must fail before Harbor starts.
5. Reserve chained requests for prior input plus prior output context, in addition to the serialized payload and fixed safety reserve.
6. Protect the direct OpenAI credential from native Bash. Remove it from normal process inheritance, mark the model-loop process non-dumpable, require the container to lack `CAP_SYS_PTRACE`, and prove with a no-model native-Bash sentinel check that the direct environment and `/proc/<parent>/environ` do not expose it.
7. Freeze or hash the complete expected native tool schemas. Tests must reject a mutation to each schema.
8. Add no-model tests for settlement cap breaches, ledger overwrite refusal, finalization with an in-flight request, corrupt version and duplicate request IDs, an unsettled prior launch, concurrent launch exclusion, committed paid spend, chained-context reservation, and corrected paid-artifact cost validation.
9. Rerun the Docker no-model preflight because the staged runner and budget controls change. Record the new process, tool-schema, credential-isolation, wheel, commit, prompt, and verifier-handoff evidence.

## Not required

- Do not run another paid task. The immutable paid response receipts contain the token classes needed to correct accounting, the corrected spend stays below USD 0.50, and no-model provider, budget, schema, launch, and container security checks can verify the fixes.
- Do not make the wheel byte-reproducible. The canonical commit is the source pin, and each run records its own wheel hash.
- Do not add automatic recovery for an interrupted paid launch. Fail-closed manual inspection is the required behavior.
- Do not add speculative compatibility paths or copy ThinHarness product code.

## Validation required after fixes

- Run all unit, integration, lint, type, repository-boundary, and secret checks.
- Run the real Docker no-model Harbor preflight and validate its archived receipts.
- Validate the immutable paid artifacts with independently recalculated request and total costs.
- Verify the successful v2 review reports and this synthesis are committed.
- Verify the old ThinHarness worktree is unchanged, this repository has no remote, and the candidate worktree is clean.
