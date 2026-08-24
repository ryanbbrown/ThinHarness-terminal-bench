# Crack-7z Codex-subscription recovery handoff

Status: the authorized two-cell recovery completed. Both `crack-7z-hash` cells passed with reward `1.0`. The authoritative report is `reports/codex-subscription-crack-7z-recovery.json`; its durable copy and hash manifest are `artifacts/codex-subscription-crack-7z-recovery/SUMMARY.json` and `SHA256SUMS.json`.

## Matched result

| harness | reward | requests | native tools | wall / agent seconds | input / cached / output / reasoning |
|---|---:|---:|---:|---:|---:|
| Pi 0.84.2 | 1.0 | 15 | 29 | 1126.332207 / 1006.801348 | 142844 / 104960 / 2449 / 629 |
| ThinHarness 0.7.0 | 1.0 | 23 | 26 | 1091.215875 / 999.403951 | 285637 / 220160 / 2318 / 745 |

This is one matched task, not evidence that either harness is generally better. Subscription cash cost is unavailable and is not estimated.

## Trace-based comparison

Both trajectories found that `7z` was initially unavailable and the bundled John executable could not be used as-is. Both installed `p7zip-full`, built John, recovered password `1998`, and extracted `secrets/secret_file.txt` to `solution.txt`.

Pi executed 27 Bash calls and 2 native read calls. It inspected `7z2john.pl` and its README, tried two configure/build paths, completed the build, tested the 7z format, cracked the archive with the full bundled password list, and extracted the file. ThinHarness executed 26 Bash calls and no native read calls. It inspected files through Bash, installed additional build dependencies, ran two configure paths, issued six recorded build calls involving `make`, cracked with the first 4000 password-list entries plus restore/show, and extracted the file.

The gateway traces explain why fewer ThinHarness tools did not mean fewer requests. Pi returned multiple tool calls in 8 responses and completed 29 calls in 14 tool-bearing responses. ThinHarness returned multiple calls in only 2 responses and completed 26 calls in 22 tool-bearing responses. ThinHarness therefore made 8 more requests. The authoritative backend usage sums those recorded responses: ThinHarness used 142793 more input tokens and 115200 more cached input tokens; Pi used 131 more output tokens and 116 fewer reasoning tokens. The traces establish these request, serialization, and trajectory differences. They do not establish a general harness effect.

## Identity and timeout evidence

Both cells used Terminal-Bench 2.1 digest `sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`, `gpt-5.6-sol`, xhigh reasoning, low text verbosity, the frozen prompt, one attempt, concurrency one, and zero retries. cproxy remained `0.1.0` at `ef96cbaea614753171627c059297e163fed0bc53`.

The real ThinHarness receipt records commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`, transient bundle SHA-256 `8ee6a96b2b688ea99525f18a66abda68dcda860d5382738913e4b89b040ad804`, wheel SHA-256 `93e06531f85ad4fa4accf13c0207298e9b3eb66240327f321549252a43a23a35`, `provider_owns_client: true`, and effective connect, read, write, and pool timeouts of 1800 seconds.

No further model, Harbor, cproxy, subscription, direct API, or Doppler request was made while preserving and validating this evidence.
