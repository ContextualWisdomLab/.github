"""Regression tests for binary document input on the canonical Noema path."""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from scripts.ci import noema_review_document as document
from scripts.ci import noema_review_gate as noema


def _docx_bytes(*, malformed: bool = False) -> bytes:
    """Build a synthetic DOCX containing body, table, and Office Math text."""
    if malformed:
        return b"not a zip archive"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <w:body>
    <w:p><w:r><w:t>DOCX-REVIEW-MARKER</w:t></w:r><m:oMath><m:r><m:t>x+y</m:t></m:r></m:oMath></w:p>
    <w:tbl><w:tr><w:tc><w:p><w:r><w:t>table-cell-a</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>table-cell-b</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  </w:body>
</w:document>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def _pr() -> dict[str, object]:
    return {
        "headRefOid": "head",
        "baseRefOid": "base",
        "title": "document review input",
        "reviewThreads": {"nodes": []},
    }


def test_hosted_reader_bundle_is_pinned_and_local():
    """The hosted workflow must install only the reviewed local reader bundle."""
    repository_root = Path(__file__).resolve().parents[1]
    workflow = (repository_root / ".github/workflows/noema-review.yml").read_text(
        encoding="utf-8"
    )
    quality_workflow = (
        repository_root
        / ".github/workflows/agent-review-runtime-quality-ci.yml"
    ).read_text(encoding="utf-8")
    package = json.loads(
        (repository_root / "scripts/ci/noema-document-reader/package.json").read_text(
            encoding="utf-8"
        )
    )
    lock = json.loads(
        (
            repository_root / "scripts/ci/noema-document-reader/package-lock.json"
        ).read_text(encoding="utf-8")
    )

    assert "Provision local reviewed HWP document reader" in workflow
    assert 'NPM_CONFIG_IGNORE_SCRIPTS: "true"' in workflow
    assert "npm ci --ignore-scripts --omit=dev --no-audit --no-fund" in workflow
    assert "NOEMA_HWP_MCP_SOURCE=$reader_root/node_modules/hwp-mcp" in workflow
    assert package["dependencies"] == {"@rhwp/core": "0.7.7", "hwp-mcp": "0.3.0"}
    assert lock["packages"]["node_modules/hwp-mcp"]["version"] == "0.3.0"
    assert lock["packages"]["node_modules/@rhwp/core"]["version"] == "0.7.7"
    assert "requirements-noema-document-ci-hashes.txt" in workflow
    assert "python3 -m pip install --quiet --require-hashes --no-deps" in workflow
    assert "requirements-noema-document-ci-hashes.txt" in quality_workflow
    assert "Install exact Noema document dependencies" in quality_workflow


def test_docx_text_reaches_the_actual_reviewer_payload(monkeypatch):
    """The extracted document context must be inside the model request body."""
    raw = _docx_bytes()
    encoded = base64.b64encode(raw).decode("ascii")

    def fake_run(args, stdin=None):
        assert "contents/docs/review.docx?ref=head" in args[2]
        return encoded

    monkeypatch.setattr(noema, "run", fake_run)
    context = noema.build_review_context(
        "owner/repo", 7, _pr(), [("docs/review.docx", "modified")]
    )
    assert "DOCX-REVIEW-MARKER" in context
    assert "x+y" in context
    assert "table-cell-a" in context
    assert "table-cell-b" in context

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            verdict = {"decision": "comment", "summary": "checked", "findings": []}
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(verdict)}}]}
            ).encode()

    class Opener:
        def open(self, request):
            captured.update(json.loads(request.data.decode()))
            return Response()

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())
    noema.call_llm(
        "owner/repo",
        7,
        _pr(),
        "diff --git a/docs/review.docx b/docs/review.docx\n+binary\n",
        False,
        "head",
        context,
        ("docs/review.docx",),
    )
    prompt = captured["messages"][1]["content"]
    assert "DOCX-REVIEW-MARKER" in prompt
    assert "table-cell-a" in prompt


def test_malformed_docx_is_explicit_in_review_context(monkeypatch):
    """Malformed document bytes are reported instead of UTF-8 replacement text."""
    encoded = base64.b64encode(_docx_bytes(malformed=True)).decode("ascii")
    monkeypatch.setattr(noema, "run", lambda _args, stdin=None: encoded)

    context = noema.changed_file_context(
        "owner/repo", 7, "head", changed_files=[("docs/broken.docx", "modified")]
    )

    assert "### docs/broken.docx" in context
    assert "document extraction failed: DOCX archive is malformed" in context
    assert "not a zip archive" not in context


def test_hwp_reader_contract_is_local_and_fail_closed(monkeypatch):
    """HWP/HWPX use the configured local adapter and reject failed readers."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b"HWP-REVIEW-MARKER\n", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)
    assert (
        document.extract_review_document("docs/review.hwpx", b"binary")
        == "HWP-REVIEW-MARKER"
    )

    failed = document.subprocess.CompletedProcess(
        ["node"], 1, stdout=b"", stderr=b"private parser details"
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: failed)
    try:
        document.extract_review_document("docs/broken.hwp", b"binary")
    except document.DocumentReadError as exc:
        assert str(exc) == "reviewed hwp-mcp/rhwp reader failed (exit 1)"
    else:
        raise AssertionError("expected failed local HWP reader to fail closed")

    def timed_out(*args, **kwargs):
        raise document.subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(document.subprocess, "run", timed_out)
    try:
        document.extract_review_document("docs/slow.hwpx", b"binary")
    except document.DocumentReadError as exc:
        assert "timed out after" in str(exc)
    else:
        raise AssertionError("expected hung local HWP reader to fail closed")


@pytest.mark.parametrize(
    ("fixture_name", "expected_text"),
    [("simple.hwp", "안녕하세요 hwp-mcp."), ("text_only.hwpx", "hwpx 텍스트.")],
)
def test_real_hwp_mcp_fixture_text_reaches_reviewer_payload(
    monkeypatch, fixture_name, expected_text
):
    """The reviewed local hwp-mcp/rhwp fixture reaches the Noema request."""
    source = Path(os.environ.get(document.HWP_READER_ENV, ""))
    fixture = source / "test" / "fixtures" / fixture_name
    if not fixture.is_file():
        pytest.skip(
            "NOEMA_HWP_MCP_SOURCE is not configured with local reviewed fixtures"
        )

    monkeypatch.setenv(document.HWP_READER_ENV, str(source))
    encoded = base64.b64encode(fixture.read_bytes()).decode("ascii")
    monkeypatch.setattr(noema, "run", lambda _args, stdin=None: encoded)
    context = noema.build_review_context(
        "owner/repo", 7, _pr(), [(f"docs/{fixture_name}", "modified")]
    )
    assert expected_text in context
    if fixture_name == "simple.hwp":
        assert "| 이름 | 회사 |" in context
        assert "| 남대현 | 포텐랩 |" in context

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            verdict = {"decision": "comment", "summary": "checked", "findings": []}
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(verdict)}}]}
            ).encode()

    class Opener:
        def open(self, request):
            captured.update(json.loads(request.data.decode()))
            return Response()

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())
    noema.call_llm(
        "owner/repo",
        7,
        _pr(),
        f"diff --git a/docs/{fixture_name} b/docs/{fixture_name}\n+binary\n",
        False,
        "head",
        context,
        (f"docs/{fixture_name}",),
    )
    prompt = captured["messages"][1]["content"]
    assert expected_text in prompt
    if fixture_name == "simple.hwp":
        assert "| 이름 | 회사 |" in prompt
