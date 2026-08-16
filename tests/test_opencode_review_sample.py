"""Tests for deterministic head-matched review corpus sampling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_sample.py"


def load_module() -> ModuleType:
    """Load the exact sampler module without package import side effects."""
    spec = importlib.util.spec_from_file_location("opencode_review_sample", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sample = load_module()


def candidate(
    index: int,
    *,
    language: str,
    bucket: str,
    risk: str,
    defects: list[str] | None = None,
    eligible: bool = True,
) -> dict[str, Any]:
    """Build one exact-head candidate with deterministic unique identities."""
    hex_index = f"{index:064x}"
    return {
        "case_id": f"case_{index:03d}",
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": index + 1,
        "base_sha": f"{index + 1:040x}",
        "head_sha": f"{index + 2:040x}",
        "diff_sha256": f"sha256:{hex_index}",
        "context_sha256": f"sha256:{(index + 1000):064x}",
        "primary_language": language,
        "diff_size_bucket": bucket,
        "risk_class": risk,
        "defect_class_targets": defects or [risk],
        "changed_files": index + 1,
        "additions": 10 + index,
        "deletions": index,
        "full_repository_context_available": eligible,
        "same_head_review_possible": eligible,
        "independent_expert_capacity_confirmed": eligible,
    }


def inventory(*, sample_size: int = 6) -> dict[str, Any]:
    """Build a policy-complete inventory spanning required strata."""
    values = [
        candidate(0, language="python", bucket="small", risk="security"),
        candidate(1, language="rust", bucket="medium", risk="correctness"),
        candidate(
            2,
            language="typescript",
            bucket="large",
            risk="performance",
            defects=["performance", "workflow"],
        ),
        candidate(
            3,
            language="python",
            bucket="medium",
            risk="workflow",
            defects=["workflow", "documentation"],
        ),
        candidate(
            4,
            language="rust",
            bucket="large",
            risk="data_model",
            defects=["data_model"],
        ),
        candidate(
            5,
            language="go",
            bucket="small",
            risk="documentation",
            defects=["documentation"],
        ),
        candidate(6, language="go", bucket="medium", risk="security"),
        candidate(7, language="typescript", bucket="small", risk="correctness"),
    ]
    return {
        "schema_version": "1.0",
        "inventory_id": "inventory_2026_08_08",
        "generated_at": "2026-08-08T11:30:00Z",
        "sampling_policy": {
            "sample_size": sample_size,
            "minimum_primary_languages": 4,
            "required_diff_size_buckets": ["small", "medium", "large"],
            "required_risk_classes": [
                "security",
                "correctness",
                "performance",
                "workflow",
                "documentation",
                "data_model",
            ],
            "required_defect_classes": [
                "security",
                "correctness",
                "performance",
                "workflow",
                "documentation",
                "data_model",
            ],
        },
        "candidates": values,
    }


def test_sampler_is_deterministic_and_covers_required_policy() -> None:
    """A frozen seed must reproduce one policy-complete exact-head sample."""
    first = sample.sample_inventory(inventory(), seed="frozen-seed-v1")
    second = sample.sample_inventory(inventory(), seed="frozen-seed-v1")
    assert first == second
    assert first["sample_size"] == 6
    assert len(first["selected_cases"]) == 6
    assert first["selection_sha256"].startswith("sha256:")
    assert first["source_inventory_sha256"].startswith("sha256:")
    selected = first["selected_cases"]
    assert {item["diff_size_bucket"] for item in selected} == {
        "small",
        "medium",
        "large",
    }
    assert len({item["primary_language"] for item in selected}) >= 4
    assert {item["risk_class"] for item in selected} == {
        "security",
        "correctness",
        "performance",
        "workflow",
        "documentation",
        "data_model",
    }
    covered_defects = {
        defect for item in selected for defect in item["defect_class_targets"]
    }
    assert covered_defects == {
        "security",
        "correctness",
        "performance",
        "workflow",
        "documentation",
        "data_model",
    }


def test_sampler_excludes_ineligible_candidates_and_reports_counts() -> None:
    """Candidates without all three evidence capacities must not enter the sample."""
    value = inventory(sample_size=6)
    value["candidates"].append(
        candidate(
            99,
            language="kotlin",
            bucket="small",
            risk="security",
            eligible=False,
        )
    )
    report = sample.sample_inventory(value, seed="seed")
    assert report["eligible_candidate_count"] == 8
    assert report["excluded_candidate_count"] == 1
    assert "case_099" not in {item["case_id"] for item in report["selected_cases"]}


def test_different_seeds_change_tie_breaks_without_breaking_policy() -> None:
    """Seeded tie-breaking may vary membership while every hard quota remains true."""
    value = inventory(sample_size=6)
    for index in range(8, 20):
        value["candidates"].append(
            candidate(
                index,
                language=("python", "rust", "typescript", "go")[index % 4],
                bucket=("small", "medium", "large")[index % 3],
                risk=(
                    "security",
                    "correctness",
                    "performance",
                    "workflow",
                    "documentation",
                    "data_model",
                )[index % 6],
            )
        )
    first = sample.sample_inventory(value, seed="seed-a")
    second = sample.sample_inventory(value, seed="seed-b")
    assert first["selection_sha256"] != second["selection_sha256"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "unknown fields"),
        (
            lambda value: value["sampling_policy"].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["candidates"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["candidates"][0].update({"head_sha": "main"}),
            "head_sha",
        ),
        (
            lambda value: value["candidates"][0].update(
                {"full_repository_context_available": 1}
            ),
            "boolean",
        ),
        (
            lambda value: value["sampling_policy"].update({"sample_size": True}),
            "integer",
        ),
        (
            lambda value: value["sampling_policy"].update(
                {"required_risk_classes": ["security", "Security"]}
            ),
            "duplicates",
        ),
    ],
)
def test_sampler_rejects_malformed_or_extensible_evidence(
    mutate: Any, message: str
) -> None:
    """Sampling evidence must fail closed at every governed schema layer."""
    value = inventory()
    mutate(value)
    with pytest.raises(sample.CorpusSamplingError, match=message):
        sample.validate_inventory(value)


def test_sampler_rejects_duplicate_exact_head_identity() -> None:
    """The same repository, PR, and immutable head must not appear twice."""
    value = inventory()
    duplicate = dict(value["candidates"][0])
    duplicate["case_id"] = "different_case_id"
    value["candidates"].append(duplicate)
    with pytest.raises(sample.CorpusSamplingError, match="exact-head identity"):
        sample.validate_inventory(value)


def test_sampler_rejects_insufficient_eligible_policy_coverage() -> None:
    """An underpowered inventory must be distinguished from malformed evidence."""
    value = inventory()
    value["candidates"] = value["candidates"][:3]
    with pytest.raises(sample.InsufficientCorpusError, match="sample_size"):
        sample.sample_inventory(value, seed="seed")


def test_sampler_rejects_missing_required_stratum() -> None:
    """Selection must fail rather than silently omit a required defect stratum."""
    value = inventory()
    value["candidates"] = [
        item for item in value["candidates"] if item["risk_class"] != "data_model"
    ]
    with pytest.raises(sample.InsufficientCorpusError, match="required coverage"):
        sample.sample_inventory(value, seed="seed")


def test_load_json_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    """JSON evidence must reject ambiguous keys and Python non-finite extensions."""
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(sample.CorpusSamplingError, match="duplicate JSON key"):
        sample.load_json(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value": NaN}')
    with pytest.raises(sample.CorpusSamplingError, match="non-finite JSON number"):
        sample.load_json(nonfinite)


def test_cli_writes_atomic_report_and_uses_stable_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI must distinguish success, malformed input, and insufficient inventory."""
    source = tmp_path / "inventory.json"
    output = tmp_path / "nested" / "sample.json"
    source.write_text(json.dumps(inventory()), encoding="utf-8")
    assert sample.main(["--input", str(source), "--output", str(output), "--seed", "s"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["sample_size"] == 6
    assert not output.with_name(f".{output.name}.tmp").exists()

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    assert sample.main(["--input", str(malformed), "--output", str(output)]) == 2
    assert "corpus inventory rejected" in capsys.readouterr().err

    insufficient = inventory()
    insufficient["candidates"] = insufficient["candidates"][:2]
    source.write_text(json.dumps(insufficient), encoding="utf-8")
    assert sample.main(["--input", str(source), "--output", str(output)]) == 3
    assert "corpus inventory insufficient" in capsys.readouterr().err


def test_public_sampler_callables_have_docstrings() -> None:
    """Every production class and function must remain beginner-readable."""
    missing = [
        name
        for name, value in vars(sample).items()
        if not name.startswith("_")
        and (isinstance(value, type) or callable(value))
        and getattr(value, "__module__", None) == sample.__name__
        and not getattr(value, "__doc__", None)
    ]
    assert missing == []
