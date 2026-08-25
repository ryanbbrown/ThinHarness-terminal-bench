# Additional ten-task direct matched preparation

## Scope

This preparation freezes 10 fresh Terminal-Bench 2.1 tasks and 20 future paid cells. It launches nothing. No preparation entry point imports Harbor, opens a network client, reads credentials, invokes Doppler, or creates a fake provider cell. The frozen order is Pi and then native ThinHarness for each task.

## Complete population and exclusions

The frozen catalog contains all 89 task packages from `terminal-bench/terminal-bench-2-1@sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`. Each row includes its package digest, task TOML hash, instruction hash, deterministic task-tree manifest hash, and all proxy inputs. The baseline is publication commit `70f5a7b69e7cbbcd09464e275b5a75a8821baa7f`.

The exclusion union has 36 tasks with prior real, attempted, consumed, selected-for-real, or replicate evidence. This leaves 53 eligible tasks. `mteb-retrieve`, `mteb-leaderboard`, and `large-scale-text-editing` had only rejected or first-not-selected mentions, so those mentions do not create qualifying evidence. The complete proof is in `configs/direct-openai-additional-10-exclusion-proof.json`.

## Expense proxy and strata

The proxy uses only frozen package metadata. It min-max normalizes the complete eligible population. The weights are expert time 30%, agent timeout 15%, verifier timeout 15%, CPU 10%, memory 10%, storage 5%, and image/build burden 15%. Image/build burden uses build timeout 20%, environment context bytes 40%, Dockerfile instruction count 20%, and Dockerfile COPY/ADD count 20%. A missing expert estimate gets the highest normalized burden. Constant dimensions normalize to zero. Ties use the task name in ascending bytewise order.

The ordered eligible population splits into 18 low, 18 medium, and 17 high tasks. Boundaries are score plus task name: low `1.811838/build-cython-ext` through `4.255476/llm-inference-batching-scheduler`; medium `4.326031/mteb-retrieve` through `13.733106/torch-pipeline-parallelism`; high `13.733107/torch-tensor-parallelism` through `55.070327/caffe-cifar-10`. Selection uses evenly spaced ranks within each stratum. The allocation is 3/3/4. The remainder goes to high to cover more infrastructure and expense risk.

## Selected resources

| Stratum | Task | Score | Expert min | Agent s | Verifier s | CPU | Memory MiB | Storage MiB | Environment bytes | Dockerfile instructions | COPY/ADD | Image |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| low | `build-cython-ext` | 1.811838 | 60.0 | 900 | 900 | 1 | 2048 | 10240 | 395 | 4 | 0 | `alexgshaw/build-cython-ext:20251031` |
| low | `largest-eigenval` | 2.729880 | 60.0 | 900 | 900 | 1 | 2048 | 10240 | 3195 | 5 | 2 | `alexgshaw/largest-eigenval:20251031` |
| low | `llm-inference-batching-scheduler` | 4.255476 | 45.0 | 1800 | 1800 | 1 | 2048 | 10240 | 111925 | 3 | 1 | `alexgshaw/llm-inference-batching-scheduler:20251031` |
| medium | `mteb-retrieve` | 4.326031 | 15.0 | 1800 | 1800 | 1 | 2048 | 10240 | 2660 | 6 | 1 | `alexgshaw/mteb-retrieve:20260430` |
| medium | `schemelike-metacircular-eval` | 9.569140 | 300.0 | 2400 | 2400 | 1 | 2048 | 10240 | 109675 | 4 | 2 | `alexgshaw/schemelike-metacircular-eval:20251031` |
| medium | `torch-pipeline-parallelism` | 13.733106 | 240.0 | 900 | 900 | 1 | 8192 | 10240 | 200 | 2 | 0 | `alexgshaw/torch-pipeline-parallelism:20251031` |
| high | `torch-tensor-parallelism` | 13.733107 | 240.0 | 900 | 900 | 1 | 8192 | 10240 | 201 | 2 | 0 | `alexgshaw/torch-tensor-parallelism:20251031` |
| high | `feal-linear-cryptanalysis` | 16.834119 | 960.0 | 1800 | 1800 | 1 | 2048 | 10240 | 11336 | 10 | 1 | `alexgshaw/feal-linear-cryptanalysis:20251031` |
| high | `fix-ocaml-gc` | 26.369873 | 1440.0 | 3600 | 3600 | 1 | 2048 | 10240 | 583 | 5 | 0 | `alexgshaw/fix-ocaml-gc:20251031` |
| high | `caffe-cifar-10` | 55.070327 | missing→high | 3600 | 1200 | 4 | 8192 | 10240 | 509 | 4 | 0 | `alexgshaw/caffe-cifar-10:20260403` |

The full eligible population, scores, strata, and chosen flags are in `reports/direct-openai-additional-10-population.json`.

## Unchanged direct matched method

Pi stays at 0.84.2. Native ThinHarness stays at 0.7.0 and commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`. Both use the frozen Pi prompt and native tool schemas with direct OpenAI `gpt-5.6-sol`, xhigh reasoning, low verbosity, timeout-fixed provider behavior, Harbor Docker isolation, concurrency one, one attempt, zero retries, and Pi-then-Thin order. The runner specification hashes this identity.

Every future cell must use atomic and fsynced progress, event, outcome, and cell checkpoints. A request-start marker consumes a cell forever. A restart skips every consumed cell, including interrupted and failed cells. A pre-request infrastructure failure is preserved separately and stops the runner.

## Budget and stop policy

The API-equivalent planning authorization is USD 3.00 per cell and USD 60.00 for 20 cells. USD 3.00 is the next whole-dollar ceiling above the USD 2.2227785 maximum in the preserved 40-cell run. The schedule stays USD 5.00 ordinary input, USD 0.50 cached input, USD 6.25 cache write, and USD 30.00 output per million tokens. This is not a claim about cash cost.

The future runner must reserve USD 3.00 before each cell and settle exact reported usage after each response. It stops before a new request or cell when a cap is reached. Missing usage, identity mismatch, billing failure, or confirmed quota failure consumes the current cell and stops all later cells. One in-flight response can cross a planning cap before usage is known; the runner must checkpoint it and launch nothing else.

## No-model preflight and runner work

Run `scripts/direct-openai-additional-10-checks.sh`. It performs static tests, lint, types, repository boundary and secret-pattern checks, deterministic report reproduction, and package inspection. It cannot launch model, Harbor, Docker, Doppler, credential, or fake-provider work.

The preparation does not include a paid launcher. `configs/direct-openai-additional-10-runner-spec.json` lists the exact future changes: a new namespaced constants module, parameterized reuse of the existing direct agent/gateway/container path, a budget ledger, a restart-safe sequential launcher limited to the frozen order, and separately authorized no-model Harbor and final credential-bound scripts.

## Risks

Provider policy can consume a cell before verifier handoff. The model route or availability can change. Rate and service errors consume a marked cell because retries remain zero. High-stratum tasks need up to 8192 MiB, 4 CPUs, and 3600 seconds. Static metadata does not include compressed image size, so image pulls can cost more than the proxy indicates. Image-tag availability, disk pressure, verifier timeouts, and source-wheel builds remain infrastructure risks.
