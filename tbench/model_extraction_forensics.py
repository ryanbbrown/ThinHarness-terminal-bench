"""Reproduce redacted model-extraction request forensics from preserved evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .constants import REPOSITORY_ROOT
from .durable import atomic_json

REPORT_PATH = REPOSITORY_ROOT / "reports" / "model-extraction-request-forensics-v2.json"
ORIGINAL_ROOT = REPOSITORY_ROOT / "artifacts" / "direct-openai-additional-10-pairwise" / "cells"
V1_ROOT = REPOSITORY_ROOT / "artifacts" / "direct-openai-additional-10-thinharness-supplement-v1" / "cells"
SOURCES = {
    "original_pi": ORIGINAL_ROOT / "model-extraction-relu-logits--pi",
    "original_thinharness": ORIGINAL_ROOT / "model-extraction-relu-logits--thinharness",
    "v1_thinharness": V1_ROOT / "model-extraction-relu-logits--thinharness",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _fingerprint(value: Any) -> dict[str, Any]:
    encoded = value.encode() if isinstance(value, str) else _canonical_bytes(value)
    return {"bytes": len(encoded), "sha256": _sha256_bytes(encoded)}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not values or not all(isinstance(item, dict) for item in values):
        raise RuntimeError(f"forensic JSONL evidence is empty or malformed: {path}")
    return values


def _path_evidence(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(REPOSITORY_ROOT)), "bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(item.get("text", "") for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))


def _tool(tool: dict[str, Any]) -> dict[str, Any]:
    parameters = tool.get("parameters")
    return {
        "name": tool.get("name"),
        "type": tool.get("type"),
        "strict": {"present": "strict" in tool, "value": tool.get("strict")},
        "description": _fingerprint(tool.get("description", "")),
        "parameters": _fingerprint(parameters),
        "required": parameters.get("required") if isinstance(parameters, dict) else None,
        "properties": sorted((parameters.get("properties") or {}).keys()) if isinstance(parameters, dict) else [],
    }


def _input_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"kind": "text", **_fingerprint(value)}]
    if not isinstance(value, list):
        return [{"kind": type(value).__name__, **_fingerprint(value)}]
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            items.append({"kind": type(item).__name__, **_fingerprint(item)})
            continue
        kind = item.get("type") or item.get("role") or "object"
        redacted: dict[str, Any] = {"kind": kind, "object_sha256": _fingerprint(item)["sha256"]}
        if item.get("role") in {"developer", "system", "user"}:
            redacted["text"] = _fingerprint(_content_text(item.get("content")))
        if item.get("type") == "function_call":
            redacted.update({"name": item.get("name"), "arguments": _fingerprint(item.get("arguments", ""))})
        if item.get("type") == "function_call_output":
            redacted["output"] = _fingerprint(item.get("output", ""))
        items.append(redacted)
    return items


def _response_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for item in response.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "function_call":
            calls.append({"name": item.get("name"), "arguments": _fingerprint(item.get("arguments", ""))})
    return calls


def _request_rows(cell_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    audit = _jsonl(cell_root / "gateway-audit.jsonl")
    markers = _jsonl(cell_root / "MODEL_REQUEST_STARTED.jsonl")
    if len(audit) != len(markers):
        raise RuntimeError(f"request marker denominator differs: {cell_root}")
    rows: list[dict[str, Any]] = []
    for index, (record, marker) in enumerate(zip(audit, markers, strict=True)):
        request = record.get("request")
        response = record.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict):
            raise RuntimeError(f"request or response evidence is malformed: {cell_root}")
        previous = request.get("previous_response_id")
        prior_response = audit[index - 1]["response"].get("id") if index else None
        rows.append(
            {
                "sequence": index + 1,
                "status": record.get("status"),
                "audited_downstream_request_sha256": record.get("request_sha256"),
                "upstream_payload_sha256": marker.get("payload_sha256"),
                "gateway_stream_false_transform": record.get("request_sha256") != marker.get("payload_sha256"),
                "request_keys": sorted(request),
                "input": _input_items(request.get("input")),
                "previous_response_id": {
                    "present": "previous_response_id" in request,
                    "sha256": _fingerprint(previous)["sha256"] if isinstance(previous, str) else None,
                    "links_exactly_to_prior_response": previous == prior_response if index else None,
                },
                "tool_choice": {"present": "tool_choice" in request, "value": request.get("tool_choice")},
                "parallel_tool_calls": {"present": "parallel_tool_calls" in request, "value": request.get("parallel_tool_calls")},
                "response_output_types": [item.get("type") for item in response.get("output") or [] if isinstance(item, dict)],
                "response_tool_calls": _response_calls(response),
                "response_sha256": record.get("response_sha256"),
                "policy_code": (response.get("error") or {}).get("code") if isinstance(response.get("error"), dict) else None,
            }
        )
    return rows, audit


def _run(label: str, cell_root: Path) -> dict[str, Any]:
    requests, audit = _request_rows(cell_root)
    first = audit[0]["request"]
    if label == "original_pi":
        messages = [
            {
                "role": item.get("role"),
                "text": _fingerprint(_content_text(item.get("content"))),
            }
            for item in first.get("input") or []
            if isinstance(item, dict) and item.get("role") in {"developer", "system", "user"}
        ]
        instructions = {"present": False, "value": None}
    else:
        messages = [{"role": "user", "text": _fingerprint(first.get("input", ""))}]
        instructions = {"present": "instructions" in first, "value": _fingerprint(first.get("instructions", ""))}
    policy = [row for row in requests if row["policy_code"] == "cyber_policy"]
    return {
        "harness": "pi" if label == "original_pi" else "thinharness",
        "request_count": len(requests),
        "statuses": [row["status"] for row in requests],
        "initial_request_sha256": audit[0].get("request_sha256"),
        "model": first.get("model"),
        "reasoning": first.get("reasoning"),
        "text": first.get("text"),
        "include": first.get("include"),
        "max_output_tokens": {"present": "max_output_tokens" in first, "value": first.get("max_output_tokens")},
        "store": {"present": "store" in first, "value": first.get("store")},
        "stream": {"present": "stream" in first, "value": first.get("stream")},
        "metadata": {"present": "metadata" in first, "value": first.get("metadata")},
        "instructions": instructions,
        "initial_messages": messages,
        "tools": [_tool(tool) for tool in first.get("tools") or [] if isinstance(tool, dict)],
        "tool_choice": {"present": "tool_choice" in first, "value": first.get("tool_choice")},
        "parallel_tool_calls": {"present": "parallel_tool_calls" in first, "value": first.get("parallel_tool_calls")},
        "previous_response_strategy": "full-history-in-input" if label == "original_pi" else "previous_response_id-plus-new-tool-results",
        "requests": requests,
        "cyber_policy_requests": policy,
        "evidence": {
            "gateway_audit": _path_evidence(cell_root / "gateway-audit.jsonl"),
            "request_markers": _path_evidence(cell_root / "MODEL_REQUEST_STARTED.jsonl"),
        },
    }


def _supporting_evidence() -> dict[str, Any]:
    paths = {
        "original_pi_native_receipt": next((SOURCES["original_pi"] / "job").glob("*/agent/pi-direct-result.json")),
        "original_pi_events": next((SOURCES["original_pi"] / "job").glob("*/agent/pi-events.jsonl")),
        "original_thinharness_native_receipt": next(
            (SOURCES["original_thinharness"] / "job").glob("*/agent/thinharness-direct-result.json")
        ),
        "original_thinharness_events": next((SOURCES["original_thinharness"] / "job").glob("*/agent/thinharness-events.jsonl")),
        "v1_thinharness_native_receipt": next((SOURCES["v1_thinharness"] / "job").glob("*/agent/thinharness-direct-result.json")),
        "v1_thinharness_events": next((SOURCES["v1_thinharness"] / "job").glob("*/agent/thinharness-events.jsonl")),
        "pi_tool_schema": REPOSITORY_ROOT / "configs/pi-native-tool-schemas.json",
        "thinharness_tool_schema": REPOSITORY_ROOT / "configs/native-tool-schemas.json",
        "frozen_prompt": REPOSITORY_ROOT / "prompts/pi-0.84.2-system-prompt.md",
        "request_construction_and_capture": REPOSITORY_ROOT / "tbench/direct_container.py",
        "gateway_transport_and_marker": REPOSITORY_ROOT / "tbench/direct_gateway.py",
        "pi_package_lock": REPOSITORY_ROOT / "configs/pi-subscription-package-lock.json",
        "thinharness_install_provenance_original": next((SOURCES["original_thinharness"] / "job").glob("*/agent/install-provenance.json")),
        "thinharness_install_provenance_v1": next((SOURCES["v1_thinharness"] / "job").glob("*/agent/install-provenance.json")),
    }
    return {name: _path_evidence(path) for name, path in paths.items()}


def build_report() -> dict[str, Any]:
    runs = {name: _run(name, root) for name, root in SOURCES.items()}
    pi = runs["original_pi"]
    original = runs["original_thinharness"]
    v1 = runs["v1_thinharness"]
    pi_user = next(item for item in pi["initial_messages"] if item["role"] == "user")["text"]
    original_user = original["initial_messages"][0]["text"]
    if pi_user != original_user or pi_user["sha256"] != "c9e179dd099065a34c362a865b0eb9fab5f7d96be582cf117e7519580c036ebe":
        raise RuntimeError("audited task instruction identity differs")
    if original["initial_request_sha256"] != v1["initial_request_sha256"]:
        raise RuntimeError("original and v1 ThinHarness initial requests differ")
    if [len(run["cyber_policy_requests"]) for run in (pi, original, v1)] != [0, 1, 1]:
        raise RuntimeError("cyber_policy outcome denominator differs")
    return {
        "schema_version": 2,
        "report_id": "model-extraction-request-forensics-v2",
        "classification": "redacted forensic report; restricted request text, tool arguments, and tool results are omitted",
        "scope": {
            "task": "model-extraction-relu-logits",
            "sources": ["original Pi", "original ThinHarness", "v1 supplemental ThinHarness"],
            "new_model_calls": 0,
            "evidence_only": True,
        },
        "findings": {
            "task_content": {
                "supported_as_sole_cause": False,
                "basis": (
                    "All three runs used the same byte-length and SHA-256 task instruction. Pi completed ten accepted "
                    "requests, while both ThinHarness runs were refused only after accepted intermediate requests."
                ),
            },
            "prompt_and_tool_packaging": {
                "different": True,
                "basis": (
                    "Pi sent a developer message and full history with Pi schemas. ThinHarness sent a longer instructions "
                    "field, native ThinHarness schemas, and previous_response_id state. Model, reasoning, verbosity, task "
                    "instruction, and four tool names matched."
                ),
                "causal_status": "confounder and possible contributor; preserved evidence does not isolate it",
            },
            "intermediate_behavior": {
                "supported_as_proximate_cause": True,
                "basis": (
                    "The first ThinHarness request was byte-identical across the original and v1 runs and was accepted. "
                    "Later tool calls and result fingerprints diverged, yet each ThinHarness run received cyber_policy only "
                    "on a request carrying a new tool result linked to prior response state."
                ),
                "confidence": "medium",
            },
            "policy_variance": {
                "ruled_out": False,
                "basis": (
                    "The provider returned the same redacted cyber_policy response hash in two runs, but no replay or "
                    "controlled package ablation exists. Policy state or policy changes cannot be measured from these traces."
                ),
            },
            "diagnosis": (
                "Intermediate model/tool behavior is the best-supported proximate cause. ThinHarness prompt, tool, and state "
                "packaging is a material confounder and may shape that behavior. Task content alone is not supported as "
                "sufficient. Provider policy variance remains possible."
            ),
            "confidence": "medium",
            "uncertainties": [
                "No request was replayed, and no model call was made for this report.",
                "Pi and ThinHarness packaging differs, so the traces do not isolate one packaging field.",
                "The provider policy classifier and policy version are not present in the evidence.",
                "Opaque encrypted reasoning content cannot be interpreted from the preserved traces.",
            ],
        },
        "exact_matches_and_differences": {
            "task_instruction_match": True,
            "task_instruction": pi_user,
            "model_reasoning_text_match": all(
                run["model"] == "gpt-5.6-sol"
                and run["reasoning"] == {"effort": "xhigh", "summary": "auto"}
                and run["text"] == {"verbosity": "low"}
                for run in runs.values()
            ),
            "tool_names_match": [tool["name"] for tool in pi["tools"]] == ["read", "bash", "edit", "write"]
            and sorted(tool["name"] for tool in original["tools"]) == ["bash", "edit", "read", "write"],
            "tool_descriptions_and_schemas_match": False,
            "tool_choice_absent_all_requests": all(not row["tool_choice"]["present"] for run in runs.values() for row in run["requests"]),
            "parallel_tool_calls_absent_all_requests": all(
                not row["parallel_tool_calls"]["present"] for run in runs.values() for row in run["requests"]
            ),
            "original_and_v1_thinharness_initial_request_match": True,
            "original_and_v1_thinharness_later_requests_match": False,
            "state_packaging_match": False,
        },
        "runs": runs,
        "policy_requests": {
            "original_thinharness": original["cyber_policy_requests"][0],
            "v1_thinharness": v1["cyber_policy_requests"][0],
            "shared_redacted_response_sha256": "254e1738341b44af7678c8b438b4575b73f8d0022b41f36383ae3ac364e3ef95",
        },
        "evidence": _supporting_evidence(),
        "reproduce": "uv run python -m tbench.model_extraction_forensics check",
    }


def write_report() -> dict[str, Any]:
    report = build_report()
    atomic_json(REPORT_PATH, report)
    return report


def check() -> dict[str, Any]:
    report = build_report()
    published = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    if published != report:
        raise RuntimeError("redacted forensic report does not reproduce")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write", "check"))
    args = parser.parse_args()
    report = write_report() if args.command == "write" else check()
    print(json.dumps({"diagnosis": report["findings"]["diagnosis"], "confidence": report["findings"]["confidence"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
