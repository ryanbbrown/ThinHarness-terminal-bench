from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tbench import direct_additional

EXPECTED_SELECTED = [
    "build-cython-ext",
    "largest-eigenval",
    "llm-inference-batching-scheduler",
    "mteb-retrieve",
    "schemelike-metacircular-eval",
    "torch-pipeline-parallelism",
    "torch-tensor-parallelism",
    "feal-linear-cryptanalysis",
    "fix-ocaml-gc",
    "caffe-cifar-10",
]
EXPECTED_EXCLUDED = {
    "break-filter-js-from-html",
    "build-pmars",
    "cobol-modernization",
    "code-from-image",
    "configure-git-webserver",
    "constraints-scheduling",
    "count-dataset-tokens",
    "crack-7z-hash",
    "custom-memory-heap-crash",
    "dna-insert",
    "extract-elf",
    "financial-document-processor",
    "fix-code-vulnerability",
    "fix-git",
    "git-leak-recovery",
    "hf-model-inference",
    "kv-store-grpc",
    "merge-diff-arc-agi-task",
    "multi-source-data-merger",
    "nginx-request-logging",
    "openssl-selfsigned-cert",
    "overfull-hbox",
    "polyglot-c-py",
    "prove-plus-comm",
    "pytorch-model-cli",
    "pytorch-model-recovery",
    "qemu-alpine-ssh",
    "qemu-startup",
    "raman-fitting",
    "regex-log",
    "reshard-c4-data",
    "sanitize-git-repo",
    "sqlite-with-gcov",
    "tune-mjcf",
    "vulnerable-secret",
    "write-compressor",
}


def _json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_catalog_proves_the_full_frozen_population() -> None:
    catalog = _json("configs/direct-openai-additional-10-catalog.json")
    rows = catalog["population"]

    assert catalog["dataset"] == {
        "digest": "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a",
        "name": "terminal-bench/terminal-bench-2-1",
        "task_count": 89,
    }
    assert len(rows) == len({row["task"] for row in rows}) == 89
    assert [row["task"] for row in rows] == sorted(row["task"] for row in rows)
    assert catalog["provenance"]["package_index_sha256"] == "dc91537b10819e788b668f1e91af589388dd3a5006f39efe29b78cda474581e6"
    assert all(row["task_package_digest"].startswith("sha256:") for row in rows)
    assert all(len(row["task_tree_manifest_sha256"]) == 64 for row in rows)


def test_exclusion_union_is_complete_and_selected_tasks_are_fresh() -> None:
    proof = _json("configs/direct-openai-additional-10-exclusion-proof.json")

    assert set(proof["excluded_tasks"]) == EXPECTED_EXCLUDED
    assert len(proof["task_evidence"]) == 36
    assert proof["population_accounting"] == {"complete": 89, "eligible": 53, "excluded": 36}
    assert proof["selected_conflicts"] == []
    assert not set(EXPECTED_SELECTED) & EXPECTED_EXCLUDED
    assert {item["task"] for item in proof["nonqualifying_prior_mentions"]} == {
        "large-scale-text-editing",
        "mteb-leaderboard",
        "mteb-retrieve",
    }


def test_scoring_selection_and_strata_reproduce_deterministically() -> None:
    expected_selection, expected_population = direct_additional.build_reports()
    selection = _json("configs/direct-openai-additional-10-selection.json")
    population = _json("reports/direct-openai-additional-10-population.json")

    assert selection == expected_selection
    assert population == expected_population
    assert [item["task"] for item in selection["selected"]] == EXPECTED_SELECTED
    assert {name: value["count"] for name, value in selection["strata"].items()} == {"low": 18, "medium": 18, "high": 17}
    assert {name: len(value["chosen"]) for name, value in selection["strata"].items()} == {"low": 3, "medium": 3, "high": 4}
    assert selection["allocation"]["extra_task_rule"].startswith("assign the remainder to high")


def test_budget_and_fail_closed_stop_semantics_are_frozen() -> None:
    runner = _json("configs/direct-openai-additional-10-runner-spec.json")
    budget = runner["budget"]

    assert budget["per_cell_usd"] == "3.00"
    assert budget["total_usd"] == "60.00"
    assert "missing usage" in budget["missing_usage_or_identity"]
    assert "stops all future cells" in budget["missing_usage_or_identity"]
    assert "launch nothing else" in budget["stop_policy"]
    assert runner["checkpoint_contract"]["restart"].startswith("skip every consumed cell forever")


def test_exact_twenty_cell_order_is_pi_then_thinharness() -> None:
    selection = _json("configs/direct-openai-additional-10-selection.json")
    expected = [f"{task}--{harness}" for task in EXPECTED_SELECTED for harness in ("pi", "thinharness")]

    assert selection["planned_cells"] == 20
    assert selection["planned_execution_order"] == expected
    assert _json("configs/direct-openai-additional-10-runner-spec.json")["planned_execution_order"] == expected


def test_original_methodology_identities_and_evidence_are_unchanged() -> None:
    runner = _json("configs/direct-openai-additional-10-runner-spec.json")
    identity = runner["methodology_identity"]

    assert identity["pi"]["version"] == "0.84.2"
    assert identity["thinharness"] == {
        "commit": "84105f07bb9c1ad366fc8fe4fef49e700f5e88ef",
        "provider_timeout_seconds": 1800,
        "tool_execution": "sequential",
        "tool_schema_sha256": "1c1c1e985590e9980264a2e6b8364bd96f1b052c0761eed7f127ac9ab60cfd24",
        "version": "0.7.0",
    }
    assert identity["model"]["model"] == "gpt-5.6-sol"
    assert identity["model"]["reasoning"] == {"effort": "xhigh", "summary": "auto"}
    assert identity["model"]["text"] == {"verbosity": "low"}
    assert hashlib.sha256(Path("configs/direct-openai-20task-settings.json").read_bytes()).hexdigest() == (
        "79a0cd91ddff45d5e765e05b2de114c57fbd4f17d3cf15da67f28162d7f77c1e"
    )
    assert hashlib.sha256(Path("artifacts/direct-openai-20task-pairwise/SHA256SUMS.json").read_bytes()).hexdigest() == (
        "cfa1fd7618f56f08f742ed11842d536f3a9aee925614ab15ef9dc1a3e9802a31"
    )


def test_preparation_entry_point_has_no_launch_capability(tmp_path: Path) -> None:
    source_path = Path("tbench/direct_additional.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {
        node.module.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }

    assert not imports & {"harbor", "http", "socket", "subprocess", "urllib"}
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree))
    preparation_script = Path("scripts/direct-openai-additional-10-checks.sh").read_text(encoding="utf-8").lower()
    assert not any(marker in preparation_script for marker in ("harbor run", "doppler", "docker", "direct_launch", "run_gateway"))
    direct_additional.check()
    direct_additional.render(tmp_path)
    assert (tmp_path / direct_additional.SELECTION_PATH.name).read_bytes() == direct_additional.SELECTION_PATH.read_bytes()
    assert (tmp_path / direct_additional.POPULATION_REPORT_PATH.name).read_bytes() == direct_additional.POPULATION_REPORT_PATH.read_bytes()
