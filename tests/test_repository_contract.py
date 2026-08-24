from __future__ import annotations

import hashlib
import json

from tbench.constants import PROMPT_PATH, PROMPT_SHA256, REPOSITORY_ROOT
from tbench.repository_checks import check


def test_repository_contains_no_product_or_runnable_proxy_adapter() -> None:
    check()

    assert not (REPOSITORY_ROOT / "thinharness").exists()
    assert not [path for path in REPOSITORY_ROOT.rglob("adapter.py") if ".venv" not in path.parts]


def test_frozen_prompt_and_preserved_receipts_have_literal_hashes() -> None:
    evidence = REPOSITORY_ROOT / "evidence" / "preserved-direct-api-regex-log"
    expected = {
        "thinharness-result.json": "3f0f4cc637f8019e362f05c3f355cd0b2a928da443239729a0b8ec036a5bc63d",
        "trial-result.json": "a5ac8de475849a274550a14ee5bce3a886bee7a1a851fe2fd07712c4e8a08021",
        "verifier-reward.txt": "4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865",
    }

    assert hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest() == PROMPT_SHA256
    actual = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence.iterdir() if path.is_file()}
    assert {name: actual[name] for name in expected} == expected
    receipt = json.loads((evidence / "thinharness-result.json").read_text())
    trial = json.loads((evidence / "trial-result.json").read_text())
    assert receipt["response_models"] == ["gpt-5.6-sol"]
    assert receipt["usage"]["model_requests"] == 4
    assert trial["verifier_result"]["rewards"]["reward"] == 1.0
