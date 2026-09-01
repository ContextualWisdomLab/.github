"""Behavioral contracts for repository label taxonomy reconciliation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_repository_labels.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_labels", SCRIPT)
assert SPEC and SPEC.loader
LABELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LABELS)


def write_taxonomy(tmp_path, **overrides):
    """Write a compact valid taxonomy and return its path."""

    payload = {
        "schema_version": 1,
        "type": {
            "feature": "enhancement",
            "bug": "bug",
            "documentation": "documentation",
        },
        "assignments": [
            {"repository": ".github", "issue": 1582, "type": "feature"},
            {"repository": "Repo", "issue": 1, "type": "documentation"},
        ],
    }
    payload.update(overrides)
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def completed(code=0, out="", err=""):
    """Return a compact subprocess result for GitHub CLI probes."""

    return subprocess.CompletedProcess(
        args=["gh"], returncode=code, stdout=out, stderr=err
    )


def test_load_taxonomy_contracts(tmp_path) -> None:
    """Taxonomy schema, mappings, targets, and casing fail closed."""

    types, assignments = LABELS.load_taxonomy(write_taxonomy(tmp_path))
    assert types["feature"] == "enhancement"
    assert assignments[0]["repository"] == ".github"

    bad_payloads = [
        [],
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [],
            "extra": True,
        },
        {
            "schema_version": True,
            "type": {"feature": "enhancement"},
            "assignments": [],
        },
        {"schema_version": 1, "type": {}, "assignments": []},
        {
            "schema_version": 1,
            "type": {"feature": "x", "bug": "x"},
            "assignments": [],
        },
        {"schema_version": 1, "type": {"feature": 1}, "assignments": []},
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": {},
        },
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [[]],
        },
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [
                {
                    "repository": "Repo",
                    "issue": 1,
                    "type": "feature",
                    "extra": True,
                }
            ],
        },
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [
                {"repository": "bad name", "issue": 1, "type": "feature"}
            ],
        },
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [
                {"repository": "Repo", "issue": True, "type": "feature"}
            ],
        },
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [
                {"repository": "Repo", "issue": 1, "type": "bug"}
            ],
        },
        {
            "schema_version": 1,
            "type": {"feature": "enhancement"},
            "assignments": [
                {"repository": "Repo", "issue": 1, "type": "feature"},
                {"repository": "Repo", "issue": 1, "type": "feature"},
            ],
        },
    ]
    for index, payload in enumerate(bad_payloads):
        path = tmp_path / f"bad-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(LABELS.TaxonomyError):
            LABELS.load_taxonomy(path)


def test_gh_api_builds_json_and_fails_closed(monkeypatch) -> None:
    """Label API calls serialize bounded JSON and reject failed requests."""

    seen = []
    monkeypatch.setattr(
        LABELS.subprocess,
        "run",
        lambda *args, **kwargs: seen.append((args, kwargs)) or completed(out="ok"),
    )
    assert (
        LABELS._gh_api(
            "PATCH", "repos/x/y/issues/1", body={"labels": ["documentation"]}
        )
        == "ok"
    )
    assert seen[0][1]["input"] == '{"labels":["documentation"]}'

    monkeypatch.setattr(
        LABELS.subprocess,
        "run",
        lambda *args, **kwargs: completed(code=1),
    )
    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        LABELS._gh_api("GET", "repos/x/y/issues/1")


def test_label_names_accepts_github_shapes_and_rejects_malformed() -> None:
    """Issue label extraction accepts strings/objects and rejects ambiguous payloads."""

    assert LABELS._label_names({"labels": ["a", {"name": "b"}, "a"]}) == [
        "a",
        "b",
    ]
    with pytest.raises(RuntimeError, match="labels payload"):
        LABELS._label_names({"labels": {}})
    with pytest.raises(RuntimeError, match="entry"):
        LABELS._label_names({"labels": [{}]})


def test_reconcile_preserves_unmanaged_labels_and_noops(monkeypatch) -> None:
    """Only taxonomy-managed labels are replaced; unrelated workflow labels persist."""

    calls = []

    def gh_api(method, endpoint, body=None):
        calls.append((method, body))
        if method == "GET":
            return json.dumps(
                {"labels": [{"name": "status: needs-review"}, {"name": "bug"}]}
            )
        return ""

    monkeypatch.setattr(LABELS, "_gh_api", gh_api)
    LABELS.reconcile_assignment(
        {"repository": "Repo", "issue": 1, "type": "documentation"},
        {"bug": "bug", "documentation": "documentation"},
    )
    assert calls[-1] == (
        "PATCH",
        {"labels": ["status: needs-review", "documentation"]},
    )

    calls.clear()

    def converged(method, endpoint, body=None):
        calls.append((method, body))
        return json.dumps(
            {
                "labels": [
                    {"name": "status: needs-review"},
                    {"name": "documentation"},
                ]
            }
        )

    monkeypatch.setattr(LABELS, "_gh_api", converged)
    LABELS.reconcile_assignment(
        {"repository": "Repo", "issue": 1, "type": "documentation"},
        {"bug": "bug", "documentation": "documentation"},
    )
    assert calls == [("GET", None)]

    monkeypatch.setattr(LABELS, "_gh_api", lambda *args, **kwargs: "[]")
    with pytest.raises(LABELS.TaxonomyError, match="GitHub issue"):
        LABELS.reconcile_assignment(
            {"repository": "Repo", "issue": 1, "type": "documentation"},
            {"documentation": "documentation"},
        )


def test_parse_args_and_main_modes(monkeypatch, tmp_path, capsys) -> None:
    """Validation, filtering, authority, and fleet failure aggregation are enforced."""

    path = write_taxonomy(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--taxonomy", str(path), "--repository", "Repo"],
    )
    args = LABELS.parse_args()
    assert args.repository == ["Repo"]

    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=path, validate_only=True, repository=[]
        ),
    )
    assert LABELS.main() == 0

    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=path, validate_only=False, repository=[]
        ),
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN"):
        LABELS.main()

    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=path, validate_only=False, repository=["Missing"]
        ),
    )
    with pytest.raises(LABELS.TaxonomyError, match="undeclared"):
        LABELS.main()

    seen = []
    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=path, validate_only=False, repository=["Repo"]
        ),
    )
    monkeypatch.setattr(
        LABELS,
        "reconcile_assignment",
        lambda assignment, type_map: seen.append(assignment["repository"]),
    )
    assert LABELS.main() == 0
    assert seen == ["Repo"]

    seen.clear()
    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=path, validate_only=False, repository=[]
        ),
    )

    def reconcile(assignment, type_map):
        seen.append(assignment["repository"])
        if assignment["repository"] == ".github":
            raise RuntimeError("boom")

    monkeypatch.setattr(LABELS, "reconcile_assignment", reconcile)
    with pytest.raises(RuntimeError, match=r"\.github#1582"):
        LABELS.main()
    assert seen == [".github", "Repo"]
    assert "label reconciliation failed" in capsys.readouterr().err

    monkeypatch.setattr(LABELS, "reconcile_assignment", lambda *args: None)
    assert LABELS.main() == 0


def test_main_catches_supported_errors(monkeypatch, tmp_path) -> None:
    """Expected assignment failures are aggregated instead of stopping siblings."""

    path = write_taxonomy(
        tmp_path,
        assignments=[{"repository": "Repo", "issue": 1, "type": "feature"}],
    )
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(
        LABELS,
        "parse_args",
        lambda: argparse.Namespace(
            taxonomy=path, validate_only=False, repository=[]
        ),
    )
    exceptions = [
        LABELS.TaxonomyError("x"),
        json.JSONDecodeError("x", "x", 0),
        subprocess.TimeoutExpired("gh", 1),
    ]
    for exception in exceptions:
        monkeypatch.setattr(
            LABELS,
            "reconcile_assignment",
            lambda *args, exception=exception: (_ for _ in ()).throw(exception),
        )
        with pytest.raises(RuntimeError, match="label reconciliation failed"):
            LABELS.main()


def test_module_main_guard(monkeypatch, tmp_path) -> None:
    """The executable entry point exits successfully in validation mode."""

    path = write_taxonomy(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--taxonomy", str(path), "--validate-only"],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exc.value.code == 0
