"""Tests for filtering Gitleaks SARIF before code scanning upload."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

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


def test_filter_skips_malformed_runs_and_results():
    """Malformed SARIF runs are ignored while valid run entries are filtered."""
    sarif = {
        "runs": [
            "not-a-run-object",
            {"results": "not-a-result-list"},
            {"results": [{"classifications": ["test"]}, {"ruleId": "kept"}, "raw-result"]},
        ]
    }

    assert filter_sarif.filter_test_classified_results(sarif) == 1
    assert sarif["runs"][2]["results"] == [{"ruleId": "kept"}, "raw-result"]
    assert filter_sarif.count_results(sarif) == 2


def test_load_sarif_reports_missing_file(tmp_path):
    """Missing SARIF input exits with the path and read failure reason."""
    missing = tmp_path / "missing.sarif"

    with pytest.raises(SystemExit, match="Could not read Gitleaks SARIF file"):
        filter_sarif.load_sarif(missing)


def test_load_sarif_requires_json_object(tmp_path):
    """SARIF upload input must be a JSON object."""
    source = tmp_path / "array.sarif"
    source.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit, match="must contain a JSON object"):
        filter_sarif.load_sarif(source)


def test_main_requires_an_input_path():
    """The CLI exits with usage when no input path is supplied."""
    with pytest.raises(SystemExit, match="usage: filter_gitleaks_sarif.py"):
        filter_sarif.main([])


def test_script_entrypoint_exits_with_main_status(tmp_path, monkeypatch):
    """The module entrypoint delegates to main and preserves the status code."""
    source = tmp_path / "gitleaks.sarif"
    target = tmp_path / "upload.sarif"
    source.write_text(json.dumps({"runs": [{"results": []}]}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["filter_gitleaks_sarif.py", str(source), str(target)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(Path("scripts/ci/filter_gitleaks_sarif.py")), run_name="__main__")

    assert exc_info.value.code == 0
    assert json.loads(target.read_text(encoding="utf-8")) == {"runs": [{"results": []}]}
