from __future__ import annotations

import ast
import hashlib
import json
from fractions import Fraction
from pathlib import Path

from tbench import direct_additional

EXPECTED_SELECTED = [
    "feal-differential-cryptanalysis",
    "llm-inference-batching-scheduler",
    "schemelike-metacircular-eval",
    "adaptive-rejection-sampler",
    "path-tracing-reverse",
    "torch-pipeline-parallelism",
    "gpt2-codegolf",
    "model-extraction-relu-logits",
    "protein-assembly",
    "make-doom-for-mips",
]
EXPECTED_INCLUDED_SUBMISSIONS = {
    "2026-05-01-anthropic-claude-opus-4-7-max-terminus-2.json",
    "2026-05-01-gemini-gemini-3-pro-preview-high-gemini-cli.json",
    "2026-05-01-gemini-gemini-3-pro-preview-high-terminus-2.json",
    "2026-05-01-glm-5-1-max-claude-code.json",
    "2026-05-01-openai-gpt-5-5-xhigh-codex.json",
    "2026-05-01-openai-gpt-5-5-xhigh-terminus-2.json",
    "2026-05-05-gemini-gemini-3-1-pro-preview-high-gemini-cli.json",
    "2026-05-05-gemini-gemini-3-1-pro-preview-high-terminus-2.json",
    "2026-06-05-anthropic-claude-fable-5-high-terminus-2.json",
    "2026-06-07-anthropic-claude-fable-5-xhigh-claude-code.json",
    "2026-07-09-anthropic-claude-opus-4-8-high-claude-code.json",
    "2026-07-09-anthropic-claude-sonnet-5-high-claude-code.json",
    "2026-07-09-cursor-grok-4-5-none-cursor-cli.json",
    "2026-07-09-openai-muse-spark-1-1-xhigh-mini-swe-agent.json",
    "2026-07-11-openai-gpt-5-6-luna-max-codex.json",
    "2026-07-11-openai-gpt-5-6-terra-max-codex.json",
}
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


def _json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_official_snapshot_provenance_and_hashes_are_complete() -> None:
    manifest = _json(direct_additional.SNAPSHOT_MANIFEST_PATH)
    repository = manifest["official_sources"]["repository"]

    assert manifest["fetched_at_utc"] == "2026-08-26T01:37:37Z"
    assert repository == {
        "commit": "7131e4375048a0e408a8fb404b5f499d726b695b",
        "commit_time": "2026-08-11T13:46:41-07:00",
        "ref": "main",
        "submission_count": 20,
        "submission_glob": "leaderboard/submissions/*.json",
        "url": "https://github.com/harbor-framework/terminal-bench-2-1",
    }
    assert manifest["official_sources"]["leaderboard"]["url"] == "https://www.tbench.ai/leaderboard/terminal-bench/2.1"
    assert manifest["official_sources"]["hub_dataset"]["url"] == (
        "https://hub.harborframework.com/datasets/terminal-bench/terminal-bench-2-1/latest"
    )
    assert len(manifest["raw_files"]) == 39
    for relative, identity in manifest["raw_files"].items():
        path = direct_additional.SNAPSHOT_DIR / relative
        assert path.stat().st_size == identity["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"]
    assert manifest["derived_files"] == {
        "derived/empirical-task-outcomes.json": {
            "bytes": 453261,
            "sha256": "c539341905b5f3abb62d021fda6c9b6c6763781d1096b7f636764d0c2867bbf0",
        }
    }


def test_exact_merged_submissions_and_complete_hub_trial_sets_are_included() -> None:
    evidence = direct_additional.build_evidence_report()
    names = {Path(item["submission_file"]).name for item in evidence["submissions"]}

    assert names == EXPECTED_INCLUDED_SUBMISSIONS
    assert evidence["coverage"] == {
        "empirical_submissions": 16,
        "excluded_incomplete_hub_trial_sets": 1,
        "merged_submission_files_preserved": 20,
        "merged_without_current_hub_row": 3,
        "tasks": 89,
        "tasks_with_accepted_trials": 89,
        "tasks_without_accepted_trials": 0,
    }
    assert all(item["task_coverage"] == 89 for item in evidence["submissions"])
    assert all(
        item["minimum_raw_trials_per_task"] == item["maximum_raw_trials_per_task"] == 5
        for item in evidence["submissions"]
    )
    gpt55 = next(
        item
        for item in evidence["submissions"]
        if item["source_filter"]["model_name"] == "openai/gpt-5.5" and item["source_filter"]["agent"] == "codex"
    )
    assert gpt55["source_jobs"] == ["10e2e56b-ed31-5f65-a489-69f78b902adf"]
    assert gpt55["hub_backing_job_ids"] == ["c8fcaaeb-c49a-413a-9f8d-20bc09c53339"]


def test_disqualified_trials_are_removed_from_both_parts_of_each_rate() -> None:
    evidence = direct_additional.build_evidence_report()
    cursor = next(item for item in evidence["submissions"] if item["source_filter"]["agent"] == "cursor-cli")

    assert cursor["raw_trials"] == 445
    assert cursor["raw_successes"] == 393
    assert cursor["disqualified_trials_excluded"] == 40
    assert cursor["accepted_trials"] == 405
    assert cursor["accepted_successes"] == 353
    assert sum(row["disqualified_trials_excluded"] for row in cursor["per_task"].values()) == 40
    assert cursor["per_task"]["gpt2-codegolf"]["accepted_trials"] < 5


def test_broader_accepted_trial_aggregate_uses_exact_integer_counts() -> None:
    evidence = direct_additional.build_evidence_report()
    aggregate = evidence["aggregate_by_task"]

    assert aggregate["feal-differential-cryptanalysis"] == {
        "accepted_trials": 80,
        "rate_decimal": "1.000000",
        "rate_fraction": "1",
        "successes": 80,
    }
    assert aggregate["path-tracing-reverse"] == {
        "accepted_trials": 77,
        "rate_decimal": "0.649351",
        "rate_fraction": "50/77",
        "successes": 50,
    }
    assert aggregate["make-doom-for-mips"] == {
        "accepted_trials": 80,
        "rate_decimal": "0.025000",
        "rate_fraction": "1/40",
        "successes": 2,
    }
    assert {row["accepted_trials"] for row in aggregate.values()} == {75, 76, 77, 78, 79, 80}


def test_pi_absence_is_explicit_and_verified_pi_presence_would_take_priority() -> None:
    evidence = direct_additional.build_evidence_report()

    assert evidence["pi_by_task"] == {}
    assert evidence["pi_evidence"] == {
        "verified_pi_per_task_evidence": False,
        "repository_merged_submission_matches": 0,
        "official_hub_leaderboard_row_matches": 0,
        "public_hub_job_search_totals": [0, 0, 0],
        "rate_inference": "forbidden; no Pi rate is derived",
    }
    broader = {"successes": 8, "accepted_trials": 10, "rate_fraction": "4/5", "rate_decimal": "0.800000"}
    pi = {"successes": 1, "accepted_trials": 2, "rate_fraction": "1/2", "rate_decimal": "0.500000"}
    assert direct_additional.choose_empirical_success(pi, broader) == {**pi, "source": "verified_official_pi"}
    assert direct_additional.choose_empirical_success(None, broader) == {**broader, "source": "broader_verified_agent_aggregate"}
    assert direct_additional.choose_empirical_success(None, None)["source"] == "unobserved"


def test_closest_exact_model_comparator_is_labelled_but_not_used_for_per_task_rates() -> None:
    comparator = direct_additional.build_evidence_report()["closest_official_comparator"]

    assert comparator["submission_file"].endswith("2026-07-10-gpt-5-6-sol-max-codex.json")
    assert comparator["source_jobs"] == ["fa34c325-6014-59c4-b45b-4ed08c8719ae"]
    assert comparator["source_filter"] == {
        "agent": "codex",
        "agent_version": "0.144.0",
        "model_name": "gpt-5.6-sol",
        "reasoning_effort": "max",
    }
    assert comparator["per_task_evidence_available"] is False
    assert comparator["empirical_rate_use"] == "none"


def test_catalog_and_full_population_keep_resource_metadata_descriptive_only() -> None:
    catalog = _json(direct_additional.CATALOG_PATH)
    population = _json(direct_additional.POPULATION_REPORT_PATH)
    rows = catalog["population"]

    assert len(rows) == len({row["task"] for row in rows}) == 89
    assert [row["task"] for row in rows] == sorted(row["task"] for row in rows)
    assert catalog["dataset"]["digest"] == "sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a"
    assert "descriptive" in catalog["selection_role"]
    assert len(population["complete_population"]) == 89
    assert len(population["eligible_population"]) == 53
    assert all("expense_proxy_score" not in row and "proxy_components_normalized" not in row for row in population["complete_population"])
    assert all(row["resource_metadata_role"].startswith("descriptive only") for row in population["complete_population"])


def test_prior_evidence_union_is_unchanged_and_selected_tasks_are_fresh() -> None:
    proof = _json(direct_additional.EXCLUSION_PATH)

    assert set(proof["excluded_tasks"]) == EXPECTED_EXCLUDED
    assert len(proof["task_evidence"]) == 36
    assert proof["population_accounting"] == {"complete": 89, "eligible": 53, "excluded": 36}
    assert proof["selected_tasks"] == EXPECTED_SELECTED
    assert proof["selected_conflicts"] == []
    assert not set(EXPECTED_SELECTED) & EXPECTED_EXCLUDED
    assert {item["task"] for item in proof["nonqualifying_prior_mentions"]} == {
        "large-scale-text-editing",
        "mteb-leaderboard",
        "mteb-retrieve",
    }


def test_empirical_boundaries_strata_and_balanced_selection_reproduce() -> None:
    expected_selection, expected_population = direct_additional.build_reports()
    selection = _json(direct_additional.SELECTION_PATH)
    population = _json(direct_additional.POPULATION_REPORT_PATH)

    assert selection == expected_selection
    assert population == expected_population
    assert [item["task"] for item in selection["selected"]] == EXPECTED_SELECTED
    assert selection["stratum_definition"] == {
        "defined_before_selection": True,
        "direction": "higher success is easier",
        "easy": "accepted empirical success rate >= 3/4",
        "hard": "accepted empirical success rate < 1/2",
        "medium": "1/2 <= accepted empirical success rate < 3/4",
        "unobserved": "zero accepted official trials",
    }
    assert {name: value["count"] for name, value in selection["strata"].items()} == {
        "easy": 28,
        "medium": 14,
        "hard": 11,
        "unobserved": 0,
    }
    assert {name: len(value["chosen"]) for name, value in selection["strata"].items()} == {
        "easy": 3,
        "medium": 3,
        "hard": 4,
        "unobserved": 0,
    }
    selected_rates = [
        Fraction(item["empirical_success"]["successes"], item["empirical_success"]["accepted_trials"])
        for item in selection["selected"]
    ]
    assert selected_rates[:3] == [Fraction(1), Fraction(73, 80), Fraction(3, 4)]


def test_missing_data_has_an_explicit_stratum_and_deterministic_allocation() -> None:
    observed = {"task": "observed", "empirical_success": {"successes": 1, "accepted_trials": 2}}
    missing = {"task": "missing", "empirical_success": {"successes": 0, "accepted_trials": 0}}

    assert direct_additional._stratum(observed["empirical_success"]) == "medium"
    assert direct_additional._stratum(missing["empirical_success"]) == "unobserved"
    strata = {
        "easy": [{"task": f"e{i}"} for i in range(4)],
        "medium": [{"task": f"m{i}"} for i in range(4)],
        "hard": [{"task": f"h{i}"} for i in range(4)],
        "unobserved": [{"task": f"u{i}"} for i in range(4)],
    }
    assert direct_additional._allocate(strata) == {"easy": 2, "medium": 3, "hard": 3, "unobserved": 2}


def test_exact_twenty_cell_order_is_pi_then_thinharness() -> None:
    selection = _json(direct_additional.SELECTION_PATH)
    expected = [f"{task}--{harness}" for task in EXPECTED_SELECTED for harness in ("pi", "thinharness")]

    assert selection["planned_cells"] == 20
    assert selection["planned_execution_order"] == expected
    assert _json(direct_additional.RUNNER_SPEC_PATH)["planned_execution_order"] == expected


def test_methodology_identity_budget_and_stop_rules_are_unchanged() -> None:
    runner = _json(direct_additional.RUNNER_SPEC_PATH)
    identity = runner["methodology_identity"]
    budget = runner["budget"]

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
    assert budget["per_cell_usd"] == "3.00"
    assert budget["total_usd"] == "60.00"
    assert "missing usage" in budget["missing_usage_or_identity"]
    assert "stops all future cells" in budget["missing_usage_or_identity"]
    assert "launch nothing else" in budget["stop_policy"]
    assert runner["checkpoint_contract"]["restart"].startswith("skip every consumed cell forever")
    assert hashlib.sha256(Path("configs/direct-openai-20task-settings.json").read_bytes()).hexdigest() == (
        "79a0cd91ddff45d5e765e05b2de114c57fbd4f17d3cf15da67f28162d7f77c1e"
    )
    assert hashlib.sha256(Path("artifacts/direct-openai-20task-pairwise/SHA256SUMS.json").read_bytes()).hexdigest() == (
        "cfa1fd7618f56f08f742ed11842d536f3a9aee925614ab15ef9dc1a3e9802a31"
    )


def test_every_decision_artifact_supersedes_5feb_metadata_selection() -> None:
    selection = _json(direct_additional.SELECTION_PATH)
    runner = _json(direct_additional.RUNNER_SPEC_PATH)
    proof = _json(direct_additional.EXCLUSION_PATH)
    catalog = _json(direct_additional.CATALOG_PATH)

    for artifact in (selection, runner, proof, catalog):
        assert artifact["supersedes_preparation_commit"] == "5feb120248de092d72771ff7f9630423350daebd"
    assert selection["superseded_selection_basis"].startswith("metadata-weighted")
    assert not any(key in selection for key in ("expense_proxy", "weights", "image_build_subweights"))
    old = set(selection["superseded_selected_tasks"])
    assert set(EXPECTED_SELECTED) & old == {
        "llm-inference-batching-scheduler",
        "schemelike-metacircular-eval",
        "torch-pipeline-parallelism",
    }


def test_preparation_entry_point_has_no_launch_or_network_capability(tmp_path: Path) -> None:
    source_path = Path("tbench/direct_additional.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {alias.name.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }

    assert not imports & {"harbor", "http", "socket", "subprocess", "urllib"}
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree))
    script = Path("scripts/direct-openai-additional-10-checks.sh").read_text(encoding="utf-8").lower()
    assert not any(marker in script for marker in ("harbor run", "doppler", "docker", "direct_launch", "run_gateway"))
    assert _json(direct_additional.RUNNER_SPEC_PATH)["launch_enabled"] is False
    direct_additional.check()
    direct_additional.render(tmp_path)
    assert (
        tmp_path / direct_additional.EMPIRICAL_EVIDENCE_PATH.name
    ).read_bytes() == direct_additional.EMPIRICAL_EVIDENCE_PATH.read_bytes()
    assert (tmp_path / direct_additional.SELECTION_PATH.name).read_bytes() == direct_additional.SELECTION_PATH.read_bytes()
    assert (
        tmp_path / direct_additional.POPULATION_REPORT_PATH.name
    ).read_bytes() == direct_additional.POPULATION_REPORT_PATH.read_bytes()


def test_snapshot_is_evidence_only_and_excluded_from_packages() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    script = Path("scripts/direct-openai-additional-10-checks.sh").read_text(encoding="utf-8")

    assert '"/evidence"' in pyproject
    assert "evidence/terminal-bench-2-1-official-20260826" not in script.split("git diff --quiet", 1)[1].split("output=", 1)[0]
    assert direct_additional.SNAPSHOT_DIR.is_dir()
    assert not any(path.suffix == ".py" for path in direct_additional.SNAPSHOT_DIR.rglob("*"))
