"""Tests for filtering Gitleaks SARIF before code scanning upload."""

from __future__ import annotations

import json

import pytest

from scripts.ci import filter_gitleaks_sarif as filter_sarif


def test_filter_removes_only_test_classified_results(tmp_path, capsys):
    """Test-classified fake secret fixtures are omitted from uploaded SARIF."""
    source = tmp_path / "gitleaks.sarif"
    target = tmp_path / "upload.sarif"
    source.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {"driver": {"name": "Gitleaks"}},
                        "results": [
                            {
                                "ruleId": "github-pat",
                                "message": {"text": "fixture token"},
                                "properties": {"classifications": ["test"]},
                            },
                            {
                                "ruleId": "github-pat",
                                "message": {"text": "real token"},
                                "properties": {"classifications": ["credential"]},
                            },
                            {
                                "ruleId": "generic-api-key",
                                "message": {"text": "unclassified"},
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert filter_sarif.main([str(source), str(target)]) == 0

    uploaded = json.loads(target.read_text(encoding="utf-8"))
    assert [result["message"]["text"] for result in uploaded["runs"][0]["results"]] == [
        "real token",
        "unclassified",
    ]
    assert "Filtered 1 test-classified Gitleaks SARIF result(s); 2 upload result(s) remain." in capsys.readouterr().out


def test_filter_accepts_top_level_classifications():
    """Gitleaks result classifications are honored at the top level too."""
    sarif = {
        "runs": [
            {
                "results": [
                    {"ruleId": "github-pat", "classifications": ["TEST"]},
                    {"ruleId": "github-pat", "classifications": ["credential"]},
                ]
            }
        ]
    }

    assert filter_sarif.filter_test_classified_results(sarif) == 1
    assert sarif["runs"][0]["results"] == [
        {"ruleId": "github-pat", "classifications": ["credential"]}
    ]


def test_load_sarif_reports_invalid_json(tmp_path):
    """Invalid SARIF JSON exits with a concrete reason."""
    source = tmp_path / "broken.sarif"
    source.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SystemExit, match="is not valid JSON"):
        filter_sarif.load_sarif(source)
