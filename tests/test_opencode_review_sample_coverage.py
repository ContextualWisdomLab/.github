"""Close branch coverage for deterministic review-corpus sampling."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT_PATH = ROOT / "tests/test_opencode_review_sample.py"
MODULE_PATH = ROOT / "scripts/ci/opencode_review_sample.py"


def load_support() -> ModuleType:
    """Load the primary sampler test support without requiring a package."""
    spec = importlib.util.spec_from_file_location("opencode_review_sample_support", SUPPORT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


support = load_support()
sample = support.sample
inventory = support.inventory


def test_sampler_helper_boundaries_reject_invalid_shapes_and_scalars() -> None:
    """Low-level schema helpers must reject every unsupported JSON shape."""
    with pytest.raises(sample.CorpusSamplingError, match="must be an array"):
        sample.array_value({}, "array")
    with pytest.raises(sample.CorpusSamplingError, match="non-empty text"):
        sample.text_value(" ", "text")
    with pytest.raises(sample.CorpusSamplingError, match="positive integer"):
        sample.count_value(0, "count", positive=True)
    with pytest.raises(sample.CorpusSamplingError, match="must not be empty"):
        sample.normalized_unique_texts([], "values")
    with pytest.raises(sample.CorpusSamplingError, match="sha256"):
        sample.digest_value("sha256:nope", "digest")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"schema_version": "2.0"}), "schema_version"),
        (lambda value: value.update({"generated_at": "yesterday"}), "generated_at"),
        (
            lambda value: value["sampling_policy"].update(
                {"required_diff_size_buckets": ["tiny"]}
            ),
            "invalid values",
        ),
        (
            lambda value: value["sampling_policy"].update(
                {"minimum_primary_languages": 7}
            ),
            "exceeds sample_size",
        ),
        (
            lambda value: value["candidates"].append(
                {**value["candidates"][0], "head_sha": "f" * 40}
            ),
            "case_id duplicates",
        ),
        (
            lambda value: value["candidates"][0].update({"repository": "missing-slash"}),
            "owner/name",
        ),
        (
            lambda value: value["candidates"][0].update(
                {"diff_size_bucket": "tiny"}
            ),
            "diff_size_bucket",
        ),
        (lambda value: value.update({"candidates": []}), "must not be empty"),
    ],
)
def test_inventory_rejects_remaining_contract_violations(
    mutate: Any, message: str
) -> None:
    """Inventory metadata, policy, and candidate identities must remain strict."""
    value = inventory()
    mutate(value)
    with pytest.raises(sample.CorpusSamplingError, match=message):
        sample.validate_inventory(value)


def test_sampler_detects_unavailable_languages_and_too_small_policy() -> None:
    """Valid inventories that cannot fit hard quotas must fail as insufficient."""
    unavailable = inventory()
    for item in unavailable["candidates"]:
        item["primary_language"] = "python"
    with pytest.raises(sample.InsufficientCorpusError, match="cannot satisfy"):
        sample.sample_inventory(unavailable, seed="seed")

    too_small = inventory(sample_size=5)
    too_small["sampling_policy"]["minimum_primary_languages"] = 4
    with pytest.raises(sample.InsufficientCorpusError, match="too small"):
        sample.sample_inventory(too_small, seed="seed")


def test_sampler_round_robin_fills_remaining_capacity() -> None:
    """After hard quotas, deterministic strata rotation must fill the requested size."""
    report = sample.sample_inventory(inventory(sample_size=8), seed="fill-seed")
    assert report["sample_size"] == 8
    assert sum(item["case_count"] for item in report["stratum_counts"]) == 8


def test_direct_module_load_registers_its_support_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path-based invocation must make the fail-closed writer importable."""
    module_dir = str(MODULE_PATH.parent)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != module_dir])
    spec = importlib.util.spec_from_file_location(
        "opencode_review_sample_direct", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert sys.path[0] == module_dir


def test_load_json_wraps_syntax_and_filesystem_errors(tmp_path: Path) -> None:
    """Malformed or unavailable inventory files must produce stable bounded errors."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{")
    with pytest.raises(sample.CorpusSamplingError, match="cannot load corpus inventory"):
        sample.load_json(malformed)
    with pytest.raises(sample.CorpusSamplingError, match="cannot load corpus inventory"):
        sample.load_json(tmp_path / "absent.json")


def test_sampler_module_entrypoint_uses_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct script execution must route through the tested CLI main function."""
    source = tmp_path / "inventory.json"
    output = tmp_path / "sample.json"
    source.write_text(json.dumps(inventory()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            str(MODULE_PATH),
            "--input",
            str(source),
            "--output",
            str(output),
            "--seed",
            "entrypoint",
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    assert output.exists()
