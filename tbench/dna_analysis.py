"""Reproduce the dna-insert repeated-boundary analysis from preserved evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from .direct_constants import REPOSITORY_ROOT

EVIDENCE_ROOT = REPOSITORY_ROOT / "evidence" / "dna-insert-prompt-analysis"
REPORT_PATH = REPOSITORY_ROOT / "reports" / "dna-insert-prompt-analysis.json"
PI_CELL = REPOSITORY_ROOT / "artifacts" / "direct-openai-20task-pairwise" / "cells" / "dna-insert--pi"
THIN_CELL = REPOSITORY_ROOT / "artifacts" / "direct-openai-20task-pairwise" / "cells" / "dna-insert--thinharness"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _one(path: Path, pattern: str) -> Path:
    values = list(path.glob(pattern))
    if len(values) != 1:
        raise RuntimeError(f"expected one preserved evidence path for {pattern}")
    return values[0]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _strings(child)]
    return []


def _sequences() -> dict[str, str]:
    events = _one(PI_CELL, "job/*/agent/pi-events.jsonl")
    candidates: list[str] = []
    for line in events.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        candidates.extend(text for text in _strings(value) if ">input\n" in text and ">output\n" in text)
    if not candidates:
        raise RuntimeError("preserved dna-insert FASTA tool evidence is absent")
    text = max(candidates, key=len)
    text = text[text.index(">input\n") :]
    records: dict[str, str] = {}
    for record in text.split(">"):
        if not record.strip():
            continue
        name, *lines = record.strip().splitlines()
        if name in {"input", "output"}:
            records[name] = "".join(lines).lower()
    if set(records) != {"input", "output"}:
        raise RuntimeError("preserved dna-insert FASTA is incomplete")
    return records


def _verifier_constants() -> dict[str, str]:
    source = EVIDENCE_ROOT / "verifier-test_outputs.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    wanted = {"vector1", "vector2", "insert"}
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in wanted:
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                values[name] = value
    if set(values) != wanted:
        raise RuntimeError("preserved verifier split constants are incomplete")
    return values


def _valid_insertions(source: str, target: str) -> list[dict[str, Any]]:
    delta = len(target) - len(source)
    values = []
    for index in range(len(source) + 1):
        insert = target[index : index + delta]
        if source[:index] + insert + source[index:] == target:
            values.append(
                {
                    "split_index": index,
                    "insert": insert,
                    "input_context": f"{source[index - 7:index]}|{source[index:index + 7]}",
                    "output_context": f"{target[index - 7:index]}|{target[index:index + delta]}|{target[index + delta:index + delta + 7]}",
                }
            )
    return values


def build() -> dict[str, Any]:
    sequences = _sequences()
    verifier = _verifier_constants()
    source = sequences["input"]
    target = sequences["output"]
    all_partitions = _valid_insertions(source, target)
    if [item["split_index"] for item in all_partitions] != [213, 214, 215]:
        raise RuntimeError("dna-insert repeated-boundary partitions differ")
    partitions = [item for item in all_partitions if item["split_index"] in {213, 215}]
    hidden = [
        index
        for index in range(len(source) + 1)
        if source[:index].endswith(verifier["vector1"]) and source[index:].startswith(verifier["vector2"])
    ]
    if hidden != [213] or verifier["insert"] != partitions[0]["insert"]:
        raise RuntimeError("preserved verifier does not select the expected hidden split")
    pi_events = _one(PI_CELL, "job/*/agent/pi-events.jsonl")
    thin_audit = THIN_CELL / "gateway-audit.jsonl"
    thin_verifier = _one(THIN_CELL, "job/*/verifier/test-stdout.txt")
    pi_text = pi_events.read_text(encoding="utf-8")
    thin_text = thin_audit.read_text(encoding="utf-8")
    thin_verifier_text = thin_verifier.read_text(encoding="utf-8")
    required = {
        "pi": ("F annealing Tm: 63.484852", "R annealing Tm: 63.170057"),
        "thin": ("61.236660", "59.837385"),
        "hidden_reparse": ("66.274364", "58.082753", "8.191611"),
    }
    if not all(marker in pi_text for marker in required["pi"]):
        raise RuntimeError("preserved split-213 primer calculations are absent")
    if not all(marker in thin_text for marker in required["thin"]):
        raise RuntimeError("preserved split-215 primer calculations are absent")
    if not all(marker in thin_verifier_text for marker in required["hidden_reparse"]):
        raise RuntimeError("preserved hidden-verifier reparse calculations are absent")
    return {
        "schema_version": 1,
        "question": "Does the exact public prompt deterministically select the verifier's two-base-shifted split?",
        "answer": "No",
        "deterministic_public_split": False,
        "reason": (
            "The repeated AG permits the two endpoint 39-base insertion partitions at 213 and 215. "
            "The public instruction gives no boundary-assignment rule; a one-base intermediate split at 214 is also sequence-valid."
        ),
        "input_length": len(source),
        "output_length": len(target),
        "length_delta": len(target) - len(source),
        "all_sequence_valid_split_indices": [213, 214, 215],
        "requested_repeated_ag_endpoint_partitions": [213, 215],
        "partitions": [
            {
                **partitions[0],
                "public_requirement_met": True,
                "preserved_primer_evidence": {
                    "annealed_forward_length": 16,
                    "annealed_reverse_length": 44,
                    "forward_tm_c": 63.484852,
                    "reverse_tm_c": 63.170057,
                    "tm_delta_c": 0.314795,
                    "primer_pairs": 1,
                },
                "hidden_verifier_accepts": True,
            },
            {
                **partitions[1],
                "public_requirement_met": True,
                "preserved_primer_evidence": {
                    "annealed_forward_length": 16,
                    "annealed_reverse_length": 32,
                    "forward_tm_c": 61.236660,
                    "reverse_tm_c": 59.837385,
                    "tm_delta_c": 1.399275,
                    "primer_pairs": 1,
                },
                "hidden_verifier_accepts": False,
                "hidden_verifier_reparse": {
                    "annealed_forward_length": 18,
                    "annealed_reverse_length": 30,
                    "forward_tm_c": 66.274364,
                    "reverse_tm_c": 58.082753,
                    "tm_delta_c": 8.191611,
                },
            },
        ],
        "relationship": "split_213_insert = 'ag' + split_215_insert[:-2]",
        "verifier_hidden_split_index": 213,
        "conclusion": (
            "Both requested repeated-AG endpoint partitions convert the exact public input to the exact public output and have "
            "preserved one-pair designs that meet the stated length and Tm rules. Only split 213 matches the verifier's hidden constants."
            " The sequence also permits an intermediate split at 214, which further disproves deterministic selection."

        ),
        "evidence": {
            "public_instruction": str((EVIDENCE_ROOT / "instruction.md").relative_to(REPOSITORY_ROOT)),
            "public_instruction_sha256": _sha256(EVIDENCE_ROOT / "instruction.md"),
            "verifier_source": str((EVIDENCE_ROOT / "verifier-test_outputs.py").relative_to(REPOSITORY_ROOT)),
            "verifier_source_sha256": _sha256(EVIDENCE_ROOT / "verifier-test_outputs.py"),
            "pi_trace": str(pi_events.relative_to(REPOSITORY_ROOT)),
            "thinharness_trace": str(thin_audit.relative_to(REPOSITORY_ROOT)),
            "thinharness_verifier": str(thin_verifier.relative_to(REPOSITORY_ROOT)),
        },
        "reproduce": "uv run python -m tbench.dna_analysis --check",
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if REPORT_PATH.read_text(encoding="utf-8") != content:
            raise RuntimeError("dna-insert analysis report is not reproducible")
    else:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
