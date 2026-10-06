"""Tests for scripts/ci/issue_draft_composer.py (ADR-0022's draft-first issue composer)."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import issue_draft_composer as composer

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "issue_draft_composer.py"
SCRIPTS_CI_DIR = str(MODULE_PATH.parent)


def valid_payload(**overrides):
    """Return a minimal, valid evidence payload, with optional field overrides."""
    payload = {
        "repo": "ContextualWisdomLab/.github",
        "title": "Example drafted issue",
        "summary": "A short summary of the observed gap.",
        "findings": [
            {"description": "Something was observed.", "citation": "scripts/ci/example.py:10"},
        ],
        "source": "docs/product-technical-gap-baseline.md#2026-09-02",
        "labels": ["gap-baseline"],
    }
    payload.update(overrides)
    return payload


# --- load_draft: evidence-gate validation ---------------------------------


def test_load_draft_accepts_a_complete_payload():
    """A fully specified payload becomes a structured IssueDraft."""
    draft = composer.load_draft(valid_payload())
    assert draft.repo == "ContextualWisdomLab/.github"
    assert draft.title == "Example drafted issue"
    assert draft.findings == (
        composer.Finding(description="Something was observed.", citation="scripts/ci/example.py:10"),
    )
    assert draft.labels == ("gap-baseline",)


def test_load_draft_defaults_labels_to_empty_tuple_when_omitted():
    """labels is optional; omitting it composes a label-less draft."""
    payload = valid_payload()
    del payload["labels"]
    draft = composer.load_draft(payload)
    assert draft.labels == ()


def test_load_draft_rejects_non_object_payload():
    """A top-level non-dict payload is rejected."""
    with pytest.raises(composer.IssueDraftError, match="JSON object"):
        composer.load_draft([])  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["repo", "title", "summary", "source"])
def test_load_draft_rejects_missing_or_blank_required_strings(field):
    """Each required string field must be present and non-blank."""
    for bad_value in (None, "", "   ", 42):
        payload = valid_payload(**{field: bad_value})
        with pytest.raises(composer.IssueDraftError, match=field):
            composer.load_draft(payload)


def test_load_draft_rejects_malformed_repo():
    """repo must look like owner/repo, not a bare name or URL."""
    with pytest.raises(composer.IssueDraftError, match="owner/repo"):
        composer.load_draft(valid_payload(repo="not-a-repo-slug"))


def test_load_draft_rejects_oversized_title():
    """title beyond GitHub's 256-character limit is rejected."""
    with pytest.raises(composer.IssueDraftError, match="256"):
        composer.load_draft(valid_payload(title="x" * 257))


def test_load_draft_rejects_non_list_findings():
    """findings must be an array, not a scalar or object."""
    with pytest.raises(composer.IssueDraftError, match="findings"):
        composer.load_draft(valid_payload(findings={"not": "a list"}))


def test_load_draft_rejects_empty_findings():
    """An issue draft with zero findings has no supporting evidence."""
    with pytest.raises(composer.IssueDraftError, match="non-empty"):
        composer.load_draft(valid_payload(findings=[]))


def test_load_draft_rejects_non_object_finding_entry():
    """Each findings[] entry must itself be an object."""
    with pytest.raises(composer.IssueDraftError, match=r"findings\[0\]"):
        composer.load_draft(valid_payload(findings=["not an object"]))


@pytest.mark.parametrize("missing_field", ["description", "citation"])
def test_load_draft_rejects_finding_missing_description_or_citation(missing_field):
    """A finding lacking either half of its evidence pair is rejected."""
    finding = {"description": "d", "citation": "c"}
    del finding[missing_field]
    with pytest.raises(composer.IssueDraftError, match=missing_field):
        composer.load_draft(valid_payload(findings=[finding]))


def test_load_draft_rejects_non_list_labels():
    """labels must be an array when present."""
    with pytest.raises(composer.IssueDraftError, match="labels"):
        composer.load_draft(valid_payload(labels="not-a-list"))


def test_load_draft_rejects_invalid_label_entry():
    """Each label must be a short, safely-charactered string."""
    with pytest.raises(composer.IssueDraftError, match=r"labels\[1\]"):
        composer.load_draft(valid_payload(labels=["ok", 42]))
    with pytest.raises(composer.IssueDraftError, match=r"labels\[0\]"):
        composer.load_draft(valid_payload(labels=["x" * 51]))


# --- rendering --------------------------------------------------------------


def test_render_markdown_body_includes_summary_evidence_source_and_attribution():
    """The rendered body carries every evidence-gated section and its citation."""
    draft = composer.load_draft(valid_payload())
    body = composer.render_markdown_body(draft)
    assert "## Summary" in body
    assert draft.summary in body
    assert "## Evidence" in body
    assert "Something was observed. (scripts/ci/example.py:10)" in body
    assert "## Source" in body
    assert draft.source in body
    assert composer.GOVERNING_ADR in body
    assert "--create" in body


def test_render_draft_text_includes_header_with_labels():
    """The human-reviewable draft text names the target repo, title, and labels."""
    draft = composer.load_draft(valid_payload())
    text = composer.render_draft_text(draft)
    assert text.startswith("Repo: ContextualWisdomLab/.github\nTitle: Example drafted issue\nLabels: gap-baseline")
    assert "## Summary" in text


def test_render_draft_text_omits_labels_line_when_none_given():
    """No Labels: line is emitted for a label-less draft."""
    payload = valid_payload()
    del payload["labels"]
    draft = composer.load_draft(payload)
    text = composer.render_draft_text(draft)
    assert "Labels:" not in text


# --- create_issue -------------------------------------------------------------


def test_create_issue_posts_expected_argv_and_returns_url(monkeypatch):
    """create_issue calls gh api with title/body/labels and returns the created URL."""
    captured = {}

    def fake_run(args):
        captured["args"] = args
        return json.dumps({"html_url": "https://github.com/ContextualWisdomLab/.github/issues/9001"})

    monkeypatch.setattr(composer, "run", fake_run)
    draft = composer.load_draft(valid_payload(labels=["a", "b"]))
    url = composer.create_issue(draft)

    assert url == "https://github.com/ContextualWisdomLab/.github/issues/9001"
    args = captured["args"]
    assert args[:5] == ["gh", "api", "-X", "POST", "repos/ContextualWisdomLab/.github/issues"]
    assert "title=Example drafted issue" in args
    assert any(a.startswith("body=") and "## Summary" in a for a in args)
    assert "labels[]=a" in args
    assert "labels[]=b" in args


def test_create_issue_omits_label_flags_when_no_labels(monkeypatch):
    """No labels[] flags are emitted for a label-less draft."""
    monkeypatch.setattr(composer, "run", lambda args: json.dumps({"html_url": "u"}))
    payload = valid_payload()
    del payload["labels"]
    draft = composer.load_draft(payload)
    composer.create_issue(draft)


def test_create_issue_returns_empty_string_when_response_lacks_html_url(monkeypatch):
    """A malformed gh api response degrades to an empty URL rather than raising."""
    monkeypatch.setattr(composer, "run", lambda args: json.dumps({}))
    draft = composer.load_draft(valid_payload())
    assert composer.create_issue(draft) == ""


# --- CLI ----------------------------------------------------------------------


def test_main_draft_mode_prints_and_never_calls_run(monkeypatch, tmp_path, capsys):
    """Without --create, main renders the draft and makes no gh api call."""
    def fail_run(args):
        raise AssertionError(f"run() must not be called in draft mode, got {args}")

    monkeypatch.setattr(composer, "run", fail_run)
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(valid_payload()), encoding="utf-8")

    exit_code = composer.main(["--evidence-file", str(evidence_file)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Repo: ContextualWisdomLab/.github" in out
    assert "## Summary" in out


def test_main_create_mode_calls_run_and_prints_url(monkeypatch, tmp_path, capsys):
    """--create renders nothing extra; it prints only the created issue URL."""
    monkeypatch.setattr(
        composer, "run", lambda args: json.dumps({"html_url": "https://example.invalid/issues/1"})
    )
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(valid_payload()), encoding="utf-8")

    exit_code = composer.main(["--evidence-file", str(evidence_file), "--create"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "https://example.invalid/issues/1"


def test_main_reports_invalid_json_and_exits_nonzero(monkeypatch, tmp_path, capsys):
    """Malformed evidence JSON is reported to stderr with exit code 1."""
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text("{not json", encoding="utf-8")

    exit_code = composer.main(["--evidence-file", str(evidence_file)])

    assert exit_code == 1
    assert "issue_draft_composer:" in capsys.readouterr().err


def test_main_reports_missing_file_and_exits_nonzero(tmp_path, capsys):
    """A nonexistent evidence file is reported to stderr with exit code 1."""
    exit_code = composer.main(["--evidence-file", str(tmp_path / "missing.json")])

    assert exit_code == 1
    assert "issue_draft_composer:" in capsys.readouterr().err


def test_main_reports_evidence_gate_failure_and_exits_nonzero(tmp_path, capsys):
    """A structurally valid JSON file that fails the evidence gate is reported and exits 1."""
    evidence_file = tmp_path / "evidence.json"
    payload = valid_payload(findings=[])
    evidence_file.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = composer.main(["--evidence-file", str(evidence_file)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "issue_draft_composer:" in err
    assert "non-empty" in err


def test_module_falls_back_to_package_qualified_import(monkeypatch):
    """When the bare module name can't be resolved, the except branch imports it package-qualified.

    Deterministically reproduces the ModuleNotFoundError path (rather than relying on another test
    file's incidental sys.path mutation) by clearing the bare cache entry and stripping scripts/ci
    from sys.path before re-executing the module fresh under a private name.
    """
    monkeypatch.delitem(sys.modules, "pr_review_merge_scheduler", raising=False)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != SCRIPTS_CI_DIR])

    spec = importlib.util.spec_from_file_location(
        "issue_draft_composer_fallback_import_check", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module's dataclasses resolve their string annotations (from
    # __future__ import annotations) via sys.modules[cls.__module__], which only exists for a
    # normal `import` statement by default.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    assert module.run is not None
    assert module.load_draft(valid_payload()).repo == "ContextualWisdomLab/.github"


def test_module_main_guard_exits_zero(monkeypatch, tmp_path):
    """Running the module as __main__ exits with main()'s return code."""
    evidence_file = tmp_path / "evidence.json"
    evidence_file.write_text(json.dumps(valid_payload()), encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["issue_draft_composer.py", "--evidence-file", str(evidence_file)]
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path("scripts/ci/issue_draft_composer.py", run_name="__main__")
    assert exc.value.code == 0
