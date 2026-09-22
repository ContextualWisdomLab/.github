"""Tests for exact-head release dependency security evidence."""

from __future__ import annotations

import json

import pytest

from scripts.ci import release_dependency_evidence as evidence


BASE = "a" * 40
HEAD = "b" * 40


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "name": "anyio",
        "version": "4.14.2",
        "manifest": "requirements.txt",
        "relationship": "transitive",
        "license": "MIT",
        "change_type": "updated",
        "vulnerabilities": [],
    }
    row.update(overrides)
    return row


def test_receipt_binds_each_dependency_change_to_exact_head() -> None:
    receipt = evidence.build_receipt(
        [_row(), _row(name="fastapi", relationship="direct")],
        repository="ContextualWisdomLab/fast-mlsirm",
        base_sha=BASE,
        head_sha=HEAD,
    )
    assert receipt["binding"]["base_sha"] == BASE
    assert receipt["binding"]["head_sha"] == HEAD
    assert {row["relationship"] for row in receipt["dependencies"]} == {
        "direct",
        "transitive",
    }


def test_compare_api_row_without_relationship_remains_structured() -> None:
    """The documented compare response omits relationship but still covers the row."""
    row = _row()
    row.pop("relationship")
    receipt = evidence.build_receipt(
        [row],
        repository="ContextualWisdomLab/fast-mlsirm",
        base_sha=BASE,
        head_sha=HEAD,
    )
    assert receipt["dependencies"][0]["relationship"] == "not_reported_by_compare_api"


@pytest.mark.parametrize(
    "license_expression",
    ["GPL-3.0-only", "LGPL-2.1-or-later", "AGPL-3.0-only"],
)
def test_forbidden_gnu_family_license_fails_closed(license_expression: str) -> None:
    with pytest.raises(evidence.EvidenceError, match="forbidden release dependency"):
        evidence.build_receipt(
            [_row(license=license_expression)],
            repository="ContextualWisdomLab/fast-mlsirm",
            base_sha=BASE,
            head_sha=HEAD,
        )


@pytest.mark.parametrize(
    "license_expression",
    ["OTHER", "NOASSERTION", "LicenseRef-Proprietary", "MIT OR made-up-license"],
)
def test_unknown_or_unverifiable_license_fails_closed(
    license_expression: str,
) -> None:
    with pytest.raises(evidence.EvidenceError, match="invalid|unknown|unverifiable"):
        evidence.build_receipt(
            [_row(license=license_expression)],
            repository="ContextualWisdomLab/fast-mlsirm",
            base_sha=BASE,
            head_sha=HEAD,
        )


@pytest.mark.parametrize(
    ("license_expression", "canonical"),
    [
        ("MIT", "MIT"),
        ("MIT OR Apache-2.0", "MIT OR Apache-2.0"),
        ("(MIT AND BSD-3-Clause)", "(MIT AND BSD-3-Clause)"),
    ],
)
def test_valid_spdx_expressions_are_canonicalized(
    license_expression: str, canonical: str
) -> None:
    receipt = evidence.build_receipt(
        [_row(license=license_expression)],
        repository="ContextualWisdomLab/fast-mlsirm",
        base_sha=BASE,
        head_sha=HEAD,
    )
    assert receipt["dependencies"][0]["license"] == canonical


@pytest.mark.parametrize("missing", ["manifest", "license"])
def test_missing_dependency_evidence_field_fails_closed(missing: str) -> None:
    row = _row()
    row.pop(missing)
    with pytest.raises(evidence.EvidenceError, match=missing):
        evidence.build_receipt(
            [row],
            repository="ContextualWisdomLab/fast-mlsirm",
            base_sha=BASE,
            head_sha=HEAD,
        )


def test_cli_rejects_missing_evidence_file(tmp_path, capsys) -> None:
    output = tmp_path / "receipt.json"
    result = evidence.main(
        [
            "--input",
            str(tmp_path / "missing.json"),
            "--output",
            str(output),
            "--repository",
            "ContextualWisdomLab/fast-mlsirm",
            "--base-sha",
            BASE,
            "--head-sha",
            HEAD,
        ]
    )
    assert result == 2
    assert not output.exists()
    assert "missing or unsafe" in capsys.readouterr().err


def test_cli_writes_structured_receipt(tmp_path) -> None:
    source = tmp_path / "dependencies.json"
    output = tmp_path / "receipt.json"
    source.write_text(json.dumps([_row()]), encoding="utf-8")
    assert evidence.main(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            "--repository",
            "ContextualWisdomLab/fast-mlsirm",
            "--base-sha",
            BASE,
            "--head-sha",
            HEAD,
        ]
    ) == 0
    assert json.loads(output.read_text())["schema"] == "cwl-release-dependency-evidence/v1"


def test_cli_rejection_writes_exact_head_per_dependency_evidence(tmp_path) -> None:
    source = tmp_path / "dependencies.json"
    output = tmp_path / "receipt.json"
    source.write_text(
        json.dumps([_row(license="NOASSERTION"), _row(name="gpl", license="GPL-3.0-only")]),
        encoding="utf-8",
    )
    result = evidence.main(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            "--repository",
            "ContextualWisdomLab/fast-mlsirm",
            "--base-sha",
            BASE,
            "--head-sha",
            HEAD,
        ]
    )
    assert result == 2
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["result"] == "rejected"
    assert receipt["binding"] == {
        "repository": "ContextualWisdomLab/fast-mlsirm",
        "base_sha": BASE,
        "head_sha": HEAD,
    }
    assert receipt["dependency_count"] == 2
    assert {row["name"] for row in receipt["dependencies"]} == {"anyio", "gpl"}


def test_dependency_review_failure_writes_rejected_receipt(tmp_path) -> None:
    source = tmp_path / "dependencies.json"
    output = tmp_path / "receipt.json"
    source.write_text(json.dumps([_row()]), encoding="utf-8")
    result = evidence.main(
        [
            "--input",
            str(source),
            "--output",
            str(output),
            "--repository",
            "ContextualWisdomLab/fast-mlsirm",
            "--base-sha",
            BASE,
            "--head-sha",
            HEAD,
            "--dependency-review-outcome",
            "failure",
        ]
    )
    assert result == 2
    receipt = json.loads(output.read_text(encoding="utf-8"))
    assert receipt["result"] == "rejected"
    assert receipt["dependency_count"] == 1
    assert receipt["rejection_reason"] == "dependency-review action outcome: failure"
