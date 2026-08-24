# Multi-review round manifest

- Feature: native ThinHarness Terminal-Bench
- Mode: implementation
- Round: v2
- Captured at: 2026-08-24T06:28:36Z
- Base SHA: 62c43c9ba5a0da1b23f2e58f89d4d29527744175
- Snapshot SHA: 2c0bf4a6b8abe2ac401a2ce6437626fd64b46eb8
- Diff SHA-256: b55ddcb26ad6cdcc6a414bb121ebdd77696773cdded2ee7eaeee54b2e7aed7f6
- Target: .plans/native-thinharness-terminal-bench.md
- Target SHA-256: a98c0313543882d6456ac07671d7deda1fffe7c9c6569ace611b416bc94144da
- Prompt version: 3
- Prompt SHA-256: 14bd60b3fa3f5314f0ea6dd64fd7818b9020058e97738520cabbf836cc711897
- Launcher SHA-256: c61205f093c49b6b4a6b1695a18295b5eb6a3afd59887eacc400a3705d4d6026

## Reviewers

- Codex: model gpt-5.6-sol; harness codex-cli 0.147.0
- Claude: skipped
- GLM: model accounts/fireworks/models/glm-5p2; harness 2.1.224 (Claude Code) (Claude Code via Fireworks)

## Git status at capture

~~~text
(none)
~~~

## Changed files in frozen diff

~~~text
M	.gitignore
M	README.md
A	artifacts/no-model-preflight/SUMMARY.json
A	artifacts/no-model-preflight/container-preflight.json
A	artifacts/no-model-preflight/harbor-config.json
A	artifacts/no-model-preflight/host-agent-setup.json
A	artifacts/no-model-preflight/launch.json
A	artifacts/no-model-preflight/trial-result.json
A	artifacts/no-model-preflight/verifier-reward.txt
A	artifacts/paid-e2e/PROVENANCE.md
A	artifacts/paid-e2e/SHA256SUMS.json
A	artifacts/paid-e2e/api-budget.json
A	artifacts/paid-e2e/container-preflight.json
A	artifacts/paid-e2e/harbor-config.json
A	artifacts/paid-e2e/harbor-lock.json
A	artifacts/paid-e2e/host-agent-setup.json
A	artifacts/paid-e2e/implementation-budget.json
A	artifacts/paid-e2e/job-result.json
A	artifacts/paid-e2e/launch.json
A	artifacts/paid-e2e/native-thinharness-result.json
A	artifacts/paid-e2e/trial-lock.json
A	artifacts/paid-e2e/trial-result.json
A	artifacts/paid-e2e/verifier-ctrf.json
A	artifacts/paid-e2e/verifier-reward.txt
A	configs/container-runtime-requirements.txt
A	configs/frozen-settings.json
A	evidence/migration-manifest.json
A	evidence/preserved-direct-api-regex-log/PROVENANCE.md
A	evidence/preserved-direct-api-regex-log/thinharness-result.json
A	evidence/preserved-direct-api-regex-log/trial-result.json
A	evidence/preserved-direct-api-regex-log/verifier-reward.txt
A	prompts/pi-0.84.2-system-prompt.md
A	pyproject.toml
A	reports/implementation-e2e.json
A	reports/no-model-validation.md
A	scripts/container-preflight.sh
A	scripts/install-in-container.sh
A	scripts/no-model-checks.sh
A	scripts/run-paid.sh
A	tbench/__init__.py
A	tbench/agent.py
A	tbench/budget.py
A	tbench/constants.py
A	tbench/container_runner.py
A	tbench/launch.py
A	tbench/repository_checks.py
A	tbench/validate.py
A	tests/test_budget.py
A	tests/test_host_agent.py
A	tests/test_launch_contract.py
A	tests/test_repository_contract.py
A	tests/test_validator.py
A	uv.lock
~~~

## Untracked files at capture

~~~text
(none)
~~~
