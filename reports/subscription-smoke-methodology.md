# Matched Codex-subscription Terminal-Bench smoke

## Frozen design

This smoke runs `raman-fitting`, `fix-git`, `prove-plus-comm`, and `crack-7z-hash` once with Pi and once with ThinHarness. The eight Harbor cells run sequentially with one attempt, concurrency one, and zero Harbor, agent, provider, or gateway retries. `configs/subscription-smoke-selection.json` records the task metadata, image identities, deterministic low-cost selection rule, and conservative prior-paid exclusions.

Both harness loops and their native `read`, `bash`, `edit`, and `write` tools run inside the Harbor task container at `/app`. Pi is pinned to `@earendil-works/pi-coding-agent@0.84.2` with Node `22.23.1`. ThinHarness is built and installed as a wheel inside each task container from exact commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`; the unpushed commit enters through a transient local Git bundle and is not retained.

Each cell gets a short-lived authenticated host gateway. The gateway uses cproxy `0.1.0` at commit `ef96cbaea614753171627c059297e163fed0bc53` and Ryan's host Codex CLI ChatGPT OAuth to call `https://chatgpt.com/backend-api/codex/responses`. OAuth never enters a task container. The gateway rejects calls without a random per-cell bearer, logs every sanitized request and complete response, and stops after that cell. Pi 0.84.2 passes that ephemeral bearer in its process environment and its native Bash inherits process environment; ThinHarness filters it from native Bash. This is an unavoidable security-surface mismatch, but the bearer is not reusable after the cell and can reach only the audited gateway. No direct OpenAI API URL, API key, Doppler credential, or estimated cash cost is used.

## Matched settings

- Model: `gpt-5.6-sol` with exact response-model validation.
- Reasoning: `xhigh`, summary `auto`.
- Text: low verbosity.
- Prompt: frozen Pi 0.84.2 prompt, SHA-256 `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`.
- Tools: native `read`, `bash`, `edit`, and `write`, rooted at `/app`.
- Limits: 64 model requests, 128 tools where the harness exposes those limits; one Harbor attempt and no retries.

Unavoidable differences are explicit. Pi's OpenAI Responses client requires SSE, so the gateway re-emits cproxy's complete response as a valid SSE event sequence. ThinHarness consumes the same complete response as JSON. Each harness uses its own native tool schemas; names and workspace authority match, but schema details and declaration order do not. Pi serializes the frozen prompt as its native developer/system input, while ThinHarness uses its native Responses instructions field. The text and hash are identical. The gateway preserves both incoming payloads so the report can attribute payload and usage differences to recorded wire and trajectory differences.

## No-model gate

`artifacts/codex-subscription-4task-preflight/` contains two real Harbor/Docker trials, one per harness. A controlled fake cproxy contract returned one native Bash call and one final answer. Both loops executed in-container, both native Bash tools proved that no reusable OAuth or direct API credential was present, both returned to the Harbor verifier, and neither contacted the subscription backend. A separate cproxy startup validated the host Codex ChatGPT OAuth and exact upstream route with zero requests.

The gate validates complete tool schemas, roots, model payloads, response identity, token/cache/reasoning fields, retry settings, install provenance, source cleanup, logs, Harbor handoff, and artifact hashes. The expected verifier reward is zero because the controlled preflight does not solve `fix-git`.

## Authorized launch

Run only after the no-model gate passes:

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  ./scripts/run-subscription-smoke.sh
```

The command refuses existing API credentials, requires `codex login status` to report ChatGPT login, creates no dotenv file, and refuses to replace an existing durable smoke directory. Expected durable output is `artifacts/codex-subscription-4task/` plus `reports/codex-subscription-4task.json`.

## Comparison evidence

The final validator reads authoritative Codex response usage from each gateway audit, including input, cached input, cache-write when present, output, and reasoning tokens. It combines those receipts with native tool traces and Harbor timings. Pair analysis reports concrete facts: request counts, native tool sequences and arguments, serialized payload sizes, response usage, rewards, and phase timings. Missing backend fields stay `null` with an availability flag; the report does not infer them or estimate subscription cash cost.
