# Codex-subscription crack-7z recovery

## Frozen two-cell design

Run `terminal-bench/crack-7z-hash` once with Pi, then once with native ThinHarness. Both cells use Terminal-Bench 2.1 digest `sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`, `gpt-5.6-sol`, xhigh reasoning, low text verbosity, one attempt, concurrency one, and zero gateway, provider, agent, or Harbor retries.

`configs/subscription-recovery-selection.json` freezes the task metadata and preserved exclusions. Preserved real subscription evidence contains both harnesses for `raman-fitting`, both for `fix-git`, and Pi for `prove-plus-comm`. No preserved artifact or real job names `crack-7z-hash`. The launcher checks those preserved real-cell locations again before either preflight or launch and refuses a conflict. Recovery output uses the separate ID `codex-subscription-crack-7z-recovery`; prior four-task evidence remains immutable.

## Narrow timeout recovery

ThinHarness commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef` creates its own `httpx.AsyncClient` when no client is injected. The runner supplies `timeout=1800` to `OpenAIProvider` and does not supply `http_client`. Before any model request, the runner creates the native lazy client, verifies provider ownership, and verifies connect, read, write, and pool timeouts are all 1800 seconds. The ThinHarness receipt stores this controlled transport identity.

The cproxy package, commit, upstream, request transformation, gateway, and OAuth boundary are unchanged. The regression assertion against the prior runner failed with `AssertionError: injected client bypasses native provider timeout ownership` and exit 1. The new focused test constructs the native ownership path with no `http_client` argument and verifies all four effective timeout fields are 1800.

The controlled preflight uses the fake gateway contract and validates the real cproxy identity with zero upstream or subscription requests. It produces two unsolved Harbor cells and must pass all receipt validation before an authorized real launch. Its ThinHarness receipt records `provider_owns_client: true`, `provider_timeout_seconds: 1800`, and connect, read, write, and pool client timeouts of 1800.

## Authorized launch

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  ./scripts/run-subscription-smoke.sh
```

Expected real artifacts are `artifacts/codex-subscription-crack-7z-recovery/` and `reports/codex-subscription-crack-7z-recovery.json`. The command makes subscription requests. Do not run it without separate authorization after the no-model gate.
