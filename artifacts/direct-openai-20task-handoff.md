# Direct-OpenAI 20-task benchmark handoff

Status: complete. `OUTCOME.json` records 40/40 checkpointed cells. No cell was rerun. These results describe only this frozen sample. The earlier subscription sample is separate.

Authoritative machine-readable analysis: [`reports/direct-openai-20task-analysis.json`](../reports/direct-openai-20task-analysis.json). Full request bodies, batching, identities, timings, usage, costs, and trace paths: [`reports/direct-openai-20task-pairwise.json`](../reports/direct-openai-20task-pairwise.json). Immutable run root: [`artifacts/direct-openai-20task-pairwise/`](direct-openai-20task-pairwise/). Preserved process ledger: [`artifacts/direct-openai-20task-runner.log`](direct-openai-20task-runner.log).

## Design and identities

- Tasks: `cobol-modernization`, `nginx-request-logging`, `openssl-selfsigned-cert`, `polyglot-c-py`, `vulnerable-secret`, `break-filter-js-from-html`, `merge-diff-arc-agi-task`, `count-dataset-tokens`, `git-leak-recovery`, `multi-source-data-merger`, `pytorch-model-cli`, `sanitize-git-repo`, `sqlite-with-gcov`, `tune-mjcf`, `code-from-image`, `custom-memory-heap-crash`, `qemu-alpine-ssh`, `qemu-startup`, `financial-document-processor`, `dna-insert`.
- Dataset: `terminal-bench/terminal-bench-2-1@sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a`; Harbor `0.21.0`; one attempt; concurrency one; zero retries.
- Model: direct OpenAI Responses API `gpt-5.6-sol`; xhigh reasoning; low text verbosity; no cproxy or subscription bridge.
- Harnesses: Pi `0.84.2`; ThinHarness `0.7.0` at canonical commit `84105f07bb9c1ad366fc8fe4fef49e700f5e88ef`; prompt SHA-256 `bba2bb790648cb1f314bb0da22c0852429bece4446a1d7138f2ad2d66c5fad9e`.
- Canonical source identity: tree `d027dd1527c813b6e939d1ea63e8a08da86f0c0e`, commit-content SHA-256 `8467e4061800e3aae3d12e51278fb71f3bd6a95cfb9abec3a0855e495ee97f43`. Original and resumed transient bundle bytes differ, but every ThinHarness install receipt resolves to the same canonical commit.
- Runner identity started at Git `1a72a1ce44138fcc6a4a9940a8c36eab4f18e5d4` / files `b8365355010dd3d81b85e14d07f2f8bced41644be3dc1654a20516e9f3b2bec6`; the narrow recovery identity is Git `2bbb74cf2d991f89a4a94d7b1748d9a6758ba420` / files `c53749fdc7ad76376a617ed874dc72da43fdf32cd7cbfdda8a1fa8d5c6d411e3`.

## Per-cell results

Usage is ordinary / cached / cache-write / output / reasoning tokens. Batching is tool-bearing responses / multi-tool responses / maximum tools in one response. Times are wall / agent execution / verifier seconds. A dash means no verifier reward.

| cell | status / reward | requests ok/all | tools | batching | times | usage | API-equivalent USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `cobol-modernization--pi` | completed / 1.000000 | 18/18 | 21 | 17/3/3 | 306.012819/222.760726/6.032981 | 54/182513/18309/10934/7137 | 0.53397775 |
| `cobol-modernization--thinharness` | completed / 1.000000 | 13/13 | 16 | 12/2/3 | 258.377598/169.559394/7.255200 | 39/124741/18477/8788/5086 | 0.44168675 |
| `nginx-request-logging--pi` | completed / 1.000000 | 5/5 | 5 | 4/1/2 | 130.485744/44.831177/8.720650 | 15/13291/5378/2340/1029 | 0.11053300 |
| `nginx-request-logging--thinharness` | completed / 0.000000 | 3/3 | 3 | 2/1/2 | 121.856604/32.959738/7.879748 | 9/4978/4050/1699/695 | 0.07881650 |
| `openssl-selfsigned-cert--pi` | completed / 1.000000 | 4/4 | 3 | 3/0/1 | 116.384137/31.115954/6.178203 | 12/6632/3369/1659/697 | 0.07420225 |
| `openssl-selfsigned-cert--thinharness` | completed / 1.000000 | 4/4 | 3 | 3/0/1 | 127.173488/36.906244/7.496753 | 12/8314/2687/2108/1018 | 0.08425075 |
| `polyglot-c-py--pi` | completed / 1.000000 | 4/4 | 3 | 3/0/1 | 149.630113/78.165488/9.816679 | 12/9855/5860/4442/3169 | 0.17487250 |
| `polyglot-c-py--thinharness` | completed / 1.000000 | 7/7 | 6 | 6/0/1 | 146.302632/70.250389/11.597931 | 21/26588/4576/3653/2033 | 0.15158900 |
| `vulnerable-secret--pi` | model_attempt_failed / 0.000000 | 1/2 | 1 | 1/0/1 | 96.591081/13.359687/6.238218 | 3/0/1170/55/9 | 0.00897750 |
| `vulnerable-secret--thinharness` | model_attempt_failed / — | 0/1 | 0 | 0/0/0 | 92.803925/8.307841/— | 0/0/0/0/0 | 0.00000000 |
| `break-filter-js-from-html--pi` | model_attempt_failed / 0.000000 | 2/3 | 4 | 2/1/3 | 133.585806/52.857346/6.442349 | 6/1201/2394/1668/1323 | 0.06563300 |
| `break-filter-js-from-html--thinharness` | model_attempt_failed / — | 1/2 | 3 | 1/1/3 | 101.241244/19.092581/— | 3/1214/123/149/41 | 0.00586075 |
| `merge-diff-arc-agi-task--pi` | completed / 1.000000 | 12/12 | 11 | 11/0/1 | 145.926002/75.432830/9.540568 | 36/77676/12966/2809/1087 | 0.20432550 |
| `merge-diff-arc-agi-task--thinharness` | completed / 1.000000 | 9/9 | 9 | 8/1/2 | 145.947338/65.431197/11.124501 | 27/52248/8758/2887/1453 | 0.16760650 |
| `count-dataset-tokens--pi` | completed / 1.000000 | 15/15 | 22 | 14/4/3 | 201.805556/116.527534/5.917688 | 45/189514/35078/4415/2133 | 0.44666950 |
| `count-dataset-tokens--thinharness` | completed / 1.000000 | 16/16 | 22 | 15/7/2 | 224.972155/137.450670/6.617940 | 48/234911/37393/5342/2061 | 0.51166175 |
| `git-leak-recovery--pi` | completed / 1.000000 | 5/5 | 7 | 4/2/3 | 138.872063/47.108787/9.759049 | 15/9484/4540/2763/1757 | 0.11608200 |
| `git-leak-recovery--thinharness` | completed / 1.000000 | 6/6 | 10 | 5/3/3 | 169.506511/77.883068/11.107383 | 18/18804/5883/4090/2722 | 0.16896075 |
| `multi-source-data-merger--pi` | completed / 1.000000 | 4/4 | 5 | 3/1/3 | 103.597780/53.882562/8.910652 | 12/5613/5066/2875/1262 | 0.12077900 |
| `multi-source-data-merger--thinharness` | completed / 1.000000 | 4/4 | 6 | 3/1/4 | 92.552221/39.304609/10.457577 | 12/8223/4143/2397/922 | 0.10197525 |
| `pytorch-model-cli--pi` | completed / 1.000000 | 14/14 | 22 | 13/6/3 | 280.312185/129.327012/73.316905 | 42/139954/21050/6646/2126 | 0.40112950 |
| `pytorch-model-cli--thinharness` | completed / 1.000000 | 11/11 | 18 | 10/5/3 | 307.873627/142.658658/74.131875 | 33/111484/20726/6919/2495 | 0.39301450 |
| `sanitize-git-repo--pi` | completed / 1.000000 | 26/26 | 51 | 25/11/4 | 723.266462/639.801667/6.045863 | 78/2030412/127514/13674/4948 | 2.22277850 |
| `sanitize-git-repo--thinharness` | completed / 0.000000 | 14/14 | 39 | 13/11/4 | 352.729089/313.532363/8.645699 | 42/819460/101080/12388/4681 | 1.41333000 |
| `sqlite-with-gcov--pi` | completed / 1.000000 | 13/13 | 14 | 12/2/2 | 254.459342/176.337996/9.556738 | 39/238175/31486/2809/1607 | 0.40034000 |
| `sqlite-with-gcov--thinharness` | completed / 1.000000 | 8/8 | 7 | 7/0/1 | 219.530720/146.826727/10.110102 | 24/68302/17712/1855/979 | 0.20062100 |
| `tune-mjcf--pi` | completed / 0.000000 | 45/45 | 52 | 44/5/3 | 943.795776/860.941756/7.058562 | 135/705822/39580/13882/7221 | 1.01742100 |
| `tune-mjcf--thinharness` | model_attempt_failed / 0.000000 | 26/26 | 32 | 26/3/3 | 1024.287399/900.008958/34.569280 | 78/373369/30862/4544/1871 | 0.51628200 |
| `code-from-image--pi` | completed / 1.000000 | 11/11 | 11 | 10/1/2 | 152.774132/69.902229/5.810217 | 33/38123/7732/1228/510 | 0.10439150 |
| `code-from-image--thinharness` | completed / 1.000000 | 10/10 | 13 | 9/4/2 | 147.420289/61.496712/5.991377 | 30/55597/9357/1809/567 | 0.14069975 |
| `custom-memory-heap-crash--pi` | completed / 1.000000 | 21/21 | 48 | 20/15/4 | 319.791608/223.235029/17.611939 | 63/618139/58018/8168/4350 | 0.91703700 |
| `custom-memory-heap-crash--thinharness` | completed / 1.000000 | 17/17 | 29 | 16/8/3 | 209.392043/110.879492/19.651151 | 51/303637/33054/4136/1384 | 0.48274100 |
| `qemu-alpine-ssh--pi` | completed / 1.000000 | 34/34 | 42 | 33/6/3 | 478.727559/398.856017/9.794184 | 102/587941/38395/6235/2429 | 0.72149925 |
| `qemu-alpine-ssh--thinharness` | completed / 1.000000 | 27/27 | 42 | 26/8/4 | 551.855208/466.081047/10.274730 | 81/447864/36473/10371/4765 | 0.76342325 |
| `qemu-startup--pi` | completed / 1.000000 | 27/27 | 49 | 26/10/4 | 446.457406/365.460639/11.235195 | 81/578479/43618/13808/7459 | 0.97649700 |
| `qemu-startup--thinharness` | completed / 1.000000 | 24/24 | 27 | 23/3/3 | 471.961145/380.250500/11.403394 | 72/556568/41140/11243/5784 | 0.87305900 |
| `financial-document-processor--pi` | completed / 1.000000 | 12/12 | 21 | 11/1/11 | 235.756094/163.485231/10.859875 | 36/89053/17149/2832/886 | 0.23684775 |
| `financial-document-processor--thinharness` | completed / 1.000000 | 17/17 | 25 | 16/4/4 | 284.537476/209.392823/11.562679 | 51/399248/39531/6501/3014 | 0.64197775 |
| `dna-insert--pi` | completed / 1.000000 | 13/13 | 15 | 12/3/2 | 224.505277/154.829000/9.159545 | 39/89214/13114/6480/4453 | 0.32116450 |
| `dna-insert--thinharness` | completed / 0.000000 | 11/11 | 16 | 10/4/3 | 189.714897/115.320441/10.673734 | 33/105373/17743/5161/2814 | 0.31857525 |

No OpenAI response reported actual cash. Thus every per-cell and aggregate actual-cash value is null, not zero. API-equivalent cost is `(ordinary×5 + cached×0.5 + cache-write×6.25 + output×30) / 1,000,000`; reasoning is part of output and is not charged twice. The reconciled total is USD 16.63128950.

## All 20 paired comparisons

Differences are Pi minus ThinHarness. Input is total input. A dash reward means that the provider error prevented a verifier reward.

| task | reward Pi / Thin / diff | requests diff | tools diff | wall s diff | input diff | API USD diff |
|---|---:|---:|---:|---:|---:|---:|
| `cobol-modernization` | 1.000000/1.000000/0.000000 | +5 | +5 | +47.635221 | +57619 | +0.09229100 |
| `nginx-request-logging` | 1.000000/0.000000/1.000000 | +2 | +2 | +8.629140 | +9647 | +0.03171650 |
| `openssl-selfsigned-cert` | 1.000000/1.000000/0.000000 | +0 | +0 | -10.789351 | -1000 | -0.01004850 |
| `polyglot-c-py` | 1.000000/1.000000/0.000000 | -3 | -3 | +3.327481 | -15458 | +0.02328350 |
| `vulnerable-secret` | 0.000000/—/— | +1 | +1 | +3.787156 | +1173 | +0.00897750 |
| `break-filter-js-from-html` | 0.000000/—/— | +1 | +1 | +32.344562 | +2261 | +0.05977225 |
| `merge-diff-arc-agi-task` | 1.000000/1.000000/0.000000 | +3 | +2 | -0.021337 | +29645 | +0.03671900 |
| `count-dataset-tokens` | 1.000000/1.000000/0.000000 | -1 | +0 | -23.166599 | -47715 | -0.06499225 |
| `git-leak-recovery` | 1.000000/1.000000/0.000000 | -1 | -3 | -30.634448 | -10666 | -0.05287875 |
| `multi-source-data-merger` | 1.000000/1.000000/0.000000 | +0 | -1 | +11.045559 | -1687 | +0.01880375 |
| `pytorch-model-cli` | 1.000000/1.000000/0.000000 | +3 | +4 | -27.561442 | +28803 | +0.00811500 |
| `sanitize-git-repo` | 1.000000/0.000000/1.000000 | +12 | +12 | +370.537373 | +1237422 | +0.80944850 |
| `sqlite-with-gcov` | 1.000000/1.000000/0.000000 | +5 | +7 | +34.928622 | +183662 | +0.19971900 |
| `tune-mjcf` | 0.000000/0.000000/0.000000 | +19 | +20 | -80.491623 | +341228 | +0.50113900 |
| `code-from-image` | 1.000000/1.000000/0.000000 | +1 | -2 | +5.353843 | -19096 | -0.03630825 |
| `custom-memory-heap-crash` | 1.000000/1.000000/0.000000 | +4 | +19 | +110.399565 | +339478 | +0.43429600 |
| `qemu-alpine-ssh` | 1.000000/1.000000/0.000000 | +7 | +0 | -73.127649 | +142020 | -0.04192400 |
| `qemu-startup` | 1.000000/1.000000/0.000000 | +3 | +22 | -25.503739 | +24398 | +0.10343800 |
| `financial-document-processor` | 1.000000/1.000000/0.000000 | -5 | -4 | -48.781382 | -332592 | -0.40513000 |
| `dna-insert` | 1.000000/0.000000/1.000000 | +2 | -1 | +34.790380 | -20782 | +0.00258925 |

## Aggregate descriptive result

| metric | Pi | ThinHarness | Pi minus ThinHarness |
|---|---:|---:|---:|
| positive rewards / 20 | 17 | 14 | 3 |
| reported reward sum / count | 17.0/20 | 14.0/18 | not a common denominator |
| completed / model-attempt-failed | 18/2 | 17/3 | — |
| requests | 288 | 230 | 58 |
| successful requests | 286 | 228 | 58 |
| tools | 407 | 326 | 81 |
| tool-bearing / multi-tool responses | 268/72 | 211/66 | +57/+6 |
| wall seconds | 5582.736942 | 5240.035609 | 342.701333 |
| Harbor seconds | 5519.804475 | 5175.327131 | 344.477344 |
| agent-execution seconds | 3918.218667 | 3503.593452 | 414.625215 |
| verifier seconds | 238.006060 | 270.551054 | -32.544994 |
| ordinary input | 858 | 684 | 174 |
| cached input | 5611091 | 3720923 | 1890168 |
| cache-write | 491786 | 433768 | 58018 |
| total input | 6103735 | 4155375 | 1948360 |
| output | 109722 | 96040 | 13682 |
| reasoning | 55592 | 44385 | 11207 |
| API-equivalent USD | 9.175158 | 7.456131 | 1.719027 |

Of 18 pairs with two numeric rewards, Pi won 3, ThinHarness won 0, and 15 tied: 14 both passed and `tune-mjcf` was 0/0. Two pairs are incomplete because ThinHarness received no verifier reward after `cyber_policy`. This is not a population ranking.

## Trace-established causes

- **`nginx-request-logging` (+1 Pi):** ThinHarness logged `status=200`; the verifier required a whitespace-delimited three-digit status. It passed 7/8 tests. Pi passed 8/8.
- **`sanitize-git-repo` (+1 Pi):** ThinHarness removed the detected secrets and changed only the three contaminated files, but it added single quotes around two placeholders. The exact-reference check failed. Pi passed all three checks.
- **`dna-insert` (+1 Pi):** ThinHarness locally measured its primer pair at 61.236660°C and 59.837385°C. The verifier measured 66.274364°C and 58.082753°C, a difference of 8.191611°C, and failed the 5°C limit. The trace does not establish why the measurements disagree. Pi passed.
- **`vulnerable-secret`:** OpenAI returned HTTP 400 `cyber_policy`. Pi had one successful response and one Bash call before the error, then verifier reward 0. ThinHarness failed on request one and got no verifier reward. This is the final frozen outcome.
- **`break-filter-js-from-html`:** OpenAI returned HTTP 400 `cyber_policy` after 2 successful Pi requests and 1 successful ThinHarness request. Pi had no `out.html` and got reward 0; ThinHarness got no verifier reward.
- **`tune-mjcf`:** ThinHarness made 26 successful requests but Harbor stopped its agent at exactly 900 seconds, so no native final receipt exists. Both verifiers crashed with `Illegal instruction` while importing MuJoCo and recorded 0. These two rewards do not establish solution quality.

## Interruption and recovery

1. The initial process exited after `vulnerable-secret--pi` because the then-validator rejected the terminal non-credit error with `gateway audit sequence failed for vulnerable-secret--pi`. The model marker, two audit records, native receipt, Harbor result, and zero-reward verifier remained durable.
2. The first resume infrastructure attempt stopped before any new cell or model request because regenerated transient Git-bundle bytes had a different SHA. Commit `2bbb74c` changed resume identity to the canonical commit/tree while retaining receipt attestation.
3. At 08:26:06Z, the runner logged `recovered consumed cell without rerun: vulnerable-secret--pi`, appended its checkpoint, and continued. There are 40 unique real job directories and 40 unique cell IDs; no cell has a second launch.

## Historical sample — separate, not merged

The earlier post-fix subscription sample contains only `crack-7z-hash`, `configure-git-webserver`, `pytorch-model-recovery`, and `constraints-scheduling`. Pi: 3/4 positive rewards, 53 requests, 77 tools, 1913.611837 wall seconds, USD 1.664707 API-equivalent. ThinHarness: 2/4, 52 requests, 59 tools, 1788.606700 seconds, USD 1.395958. Subscription cash was unavailable. These values are not included in any 20-task total and do not support generalization.

## Validation and residual risks

- Offline evidence validation inspected all 40 checkpoints, 518 request markers, 518 audit records, 39 available native receipts, 40 install receipts, 38 verifier reward/stdout traces, and 36 CTRF files. `tune-mjcf--thinharness` has no final native receipt; the two early ThinHarness policy failures have no verifier reward. These are expected trace consequences, not missing files from successful cells.
- `SHA256SUMS.json` matches every run-root file. `SUMMARY.json` and the report are byte-identical, and rebuilding the report object from `progress.json` is exact. Usage, component costs, and the USD 16.63128950 formula reconcile.
- Freshness manifests prove 20 selected names did not occur in prior selection/evidence sources or scanned local Git refs. The execution ledger has 40 frozen Pi-then-ThinHarness cells and no duplicate or rerun.
- Secret checks passed. The OpenAI key did not enter a task container or native Bash, was not persisted, and no `sk-…` provider credential exists in repository content. Evidence can contain task-supplied dummy secrets by design.
- Final checks: 71 Pytest tests passed; Ruff passed; Pyright reported 0 errors, 0 warnings, and 0 information messages; repository/direct checks passed; wheel and sdist built. Wheel: 30 files / SHA-256 `ad0f50303efddc7c9899f3bd13abcdcf0ddf2ce61e0853c53beefb83d4853adb`. Sdist: 72 files / SHA-256 `c9e0e206fa28628aeb18fe775af63e239f6868d8069571da5635f3c29001d137`. Runtime evidence, reports, proxy adapters, product source, and bundles are excluded from both archives.
- Canonical `/Users/ryanbrown/code/thinharness` is clean at `1f0146f3b1bec31fec7939466d1d5b5d8ee042ae`; the pin exists as a commit. This repository has no remote.
- Residual risks: two pairs lack ThinHarness verifier rewards due provider policy; both `tune-mjcf` verifiers crashed; direct provider cash was not reported; results are descriptive for 20 tasks only.
