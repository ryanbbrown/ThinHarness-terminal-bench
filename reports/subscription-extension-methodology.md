# Three-pair Codex-subscription Terminal-Bench extension

## Frozen design

This extension runs `configure-git-webserver`, `pytorch-model-recovery`, and `constraints-scheduling` once with Pi and once with native ThinHarness. The six cells run in task order, Pi then ThinHarness, with one attempt, concurrency one, and zero gateway, provider, agent, or Harbor retries. The launcher validates each archived cell before it can start the next cell. It preserves partial evidence and stops if Harbor or any evidence check fails. It never replaces a prior artifact directory.

`configs/subscription-extension-selection.json` freezes the selection. It excludes every task in prior paid, launched, interrupted, or completed real evidence, including both `crack-7z-hash` recovery cells. The selected tasks are the first three after sorting the eligible minimum remaining 15-minute expert-time tier by memory, agent timeout, compressed amd64 image bytes, and task name. `mteb-retrieve` is fourth and is not selected. A preserved-name search found no selected task in the current repository's earlier refs, the preserved canonical benchmark checkout or its refs, `/Users/ryanbrown/code`, or `/Users/ryanbrown/.bb/worktrees`. The old ignored experiment path is absent, so the conservative prior exclusion set remains in force. The launcher scans preserved real artifact cells and real jobs again before preflight and before the real run.

Both harnesses retain the crack-7z native interfaces and execution policy. Pi 0.84.2 uses its native `read`, `bash`, `edit`, and `write` tools. ThinHarness 0.7.0 at `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef` uses native `BashPlugin` and `FilesystemPlugin` tools with sequential tool execution. No ThinHarness batching or product change is part of this repository. Both use `/app`, `gpt-5.6-sol`, xhigh reasoning, low text verbosity, and the frozen Pi prompt. ThinHarness uses its owned native provider client with 1800-second connect, read, write, and pool timeouts.

The bridge remains cproxy 0.1.0 at `ef96cbaea614753171627c059297e163fed0bc53`, with host Codex ChatGPT OAuth and `https://chatgpt.com/backend-api/codex/responses`. No OAuth, direct API key, or Doppler credential enters a task container. The gateway makes no retries, authenticates each cell with a short-lived bearer, and preserves sanitized request and response traces. The unavoidable Pi streaming, native schema, prompt serialization, and ephemeral bearer inheritance differences remain as documented for crack-7z.

## Fail-closed no-model gate

The controlled preflight runs all six Harbor/Docker cells with the real task identities, images, harness installations, native tools, verifier handoff, cproxy identity, and timeout-fixed setup. A fake gateway returns one native Bash call and one final response per cell and makes zero subscription requests. Each unsolved verifier must return reward zero. Finalized preflight hashes and a complete six-cell summary are mandatory before the real launcher can start.

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  ./scripts/subscription-smoke-preflight.sh
```

If any selected task, image, installation, native loop, verifier handoff, usage field, identity, or evidence check fails, the process stops before real model calls.

## Authorized six-cell run and reporting

```bash
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u OPENROUTER_API_KEY \
  TB_THINHARNESS_LOCAL_SOURCE=/Users/ryanbrown/code/thinharness \
  ./scripts/run-subscription-smoke.sh
```

The report preserves reward; exact ordinary, cached, cache-write, output, and reasoning usage; API-equivalent cost under the frozen USD 5.00 / 0.50 / 6.25 / 30.00 per million token schedule; request payload sizes and durations; tool names and arguments; tool calls per response; agent, Harbor agent-phase, verifier, and wall times; runner, model, package, image, bridge, transport, and task identities; raw traces; and hashed verifier evidence. Subscription cash cost remains unavailable. Pair and aggregate comparisons are descriptive only. The post-fix sample is exactly these three tasks plus `crack-7z-hash`; no conclusion can be generalized beyond those four tasks.
