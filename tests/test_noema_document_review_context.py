"""Regression tests for binary document input on the canonical Noema path."""

from __future__ import annotations

import base64
import io
import json
import os
import runpy
import sys
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


def _docx_entity_bytes() -> bytes:
    """Build a DOCX whose entity declaration must be rejected safely."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE w:document [<!ENTITY expansion "blocked">]>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>&expansion;</w:t></w:r></w:p></w:body>
</w:document>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def _pr() -> dict[str, object]:
    """Build a minimal PR payload shared by review-context tests."""
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
    for path in (
        "scripts/ci/noema_review_document.py",
        "scripts/ci/noema_hwp_mcp_reader.mjs",
        "scripts/ci/noema-document-reader/package.json",
        "scripts/ci/noema-document-reader/package-lock.json",
        "tests/test_noema_document_review_context.py",
    ):
        assert path in quality_workflow
    assert "tests/test_noema_document_review_context.py" in quality_workflow


def test_docx_text_reaches_the_actual_reviewer_payload(monkeypatch):
    """The extracted document context must be inside the model request body."""
    raw = _docx_bytes()
    encoded = base64.b64encode(raw).decode("ascii")

    def fake_run(args, stdin=None):
        """Return base64-encoded DOCX bytes for the requested content ref."""
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
        """Fake urllib response object supporting the context-manager protocol."""
        def __enter__(self):
            """Enter the fake response context manager."""
            return self

        def __exit__(self, *args):
            """Exit the fake response context manager."""
            return False

        def read(self):
            """Return a fake chat-completion payload as JSON bytes."""
            verdict = {"decision": "comment", "summary": "checked", "findings": []}
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(verdict)}}]}
            ).encode()

    class Opener:
        """Fake urllib opener capturing the outgoing request payload."""
        def open(self, request):
            """Capture the request body and return a fake response."""
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


def test_forbidden_docx_entities_are_explicitly_rejected():
    """Defused XML entity failures become the same bounded reader error."""
    with pytest.raises(document.DocumentReadError, match="DOCX document.xml is malformed"):
        document.extract_review_document("docs/entity.docx", _docx_entity_bytes())


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
        """Simulate a hung reviewed HWP reader subprocess."""
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
        """Fake urllib response object supporting the context-manager protocol."""
        def __enter__(self):
            """Enter the fake response context manager."""
            return self

        def __exit__(self, *args):
            """Exit the fake response context manager."""
            return False

        def read(self):
            """Return a fake chat-completion payload as JSON bytes."""
            verdict = {"decision": "comment", "summary": "checked", "findings": []}
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(verdict)}}]}
            ).encode()

    class Opener:
        """Fake urllib opener capturing the outgoing request payload."""
        def open(self, request):
            """Capture the request body and return a fake response."""
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


def test_oversize_raw_bytes_are_rejected_before_any_parsing():
    """Raw input above the bounded 8 MiB cap fails closed without inspecting the suffix."""
    raw = b"x" * (document.MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(
        document.DocumentReadError,
        match="document exceeds the bounded 8 MiB review input",
    ):
        document.extract_review_document("docs/huge.docx", raw)


def test_unsupported_suffix_is_rejected():
    """A file extension outside the supported set fails closed with the suffix named."""
    with pytest.raises(
        document.DocumentReadError,
        match=r"unsupported review document format: \.txt",
    ):
        document.extract_review_document("docs/notes.txt", b"plain text")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP archive from an arcname -> content mapping."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_docx_zip_with_too_many_entries_is_rejected():
    """A DOCX archive with more than the bounded entry count fails closed."""
    entries = {
        f"part-{index}.xml": b""
        for index in range(document.MAX_DOCUMENT_ZIP_ENTRIES + 1)
    }
    with pytest.raises(
        document.DocumentReadError, match="DOCX archive has too many entries"
    ):
        document.extract_review_document("docs/many-entries.docx", _zip_bytes(entries))


def test_docx_zip_over_the_bounded_unpacked_size_is_rejected(monkeypatch):
    """A DOCX archive whose declared unpacked size exceeds the cap fails closed."""
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 5)
    raw = _zip_bytes({"word/document.xml": b"0123456789"})
    with pytest.raises(
        document.DocumentReadError,
        match="DOCX archive exceeds the bounded unpacked size",
    ):
        document.extract_review_document("docs/oversized-unpacked.docx", raw)


def test_docx_missing_document_xml_is_rejected():
    """A DOCX archive without word/document.xml fails closed with a clear message."""
    raw = _zip_bytes({"word/other.xml": b"<x/>"})
    with pytest.raises(
        document.DocumentReadError, match="DOCX archive has no word/document.xml"
    ):
        document.extract_review_document("docs/no-document-xml.docx", raw)


def test_docx_document_xml_without_body_is_rejected():
    """A document.xml with no w:body element fails closed."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
</w:document>"""
    raw = _zip_bytes({"word/document.xml": xml.encode("utf-8")})
    with pytest.raises(
        document.DocumentReadError, match="DOCX document.xml has no document body"
    ):
        document.extract_review_document("docs/no-body.docx", raw)


def test_docx_with_only_empty_paragraphs_and_rowless_table_has_no_readable_text():
    """Empty paragraphs and a table with no populated rows leave no readable text."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr/></w:p>
    <w:tbl><w:tr></w:tr></w:tbl>
  </w:body>
</w:document>"""
    raw = _zip_bytes({"word/document.xml": xml.encode("utf-8")})
    with pytest.raises(
        document.DocumentReadError, match="DOCX contains no readable text"
    ):
        document.extract_review_document("docs/empty.docx", raw)


def test_docx_paragraph_tabs_breaks_and_table_pipe_escaping():
    """Tabs, line breaks, and a second table row exercise the paragraph/table branches."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:t>Section-Marker</w:t><w:tab/><w:t>After-Tab</w:t><w:br/><w:t>After-Break</w:t></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:t>a|b</w:t></w:p></w:tc><w:tc><w:p><w:t>c</w:t></w:p></w:tc></w:tr>
      <w:tr></w:tr>
    </w:tbl>
    <w:sectPr/>
  </w:body>
</w:document>"""
    raw = _zip_bytes({"word/document.xml": xml.encode("utf-8")})
    text = document.extract_review_document("docs/tabs-breaks.docx", raw)
    assert "Section-Marker\tAfter-Tab\nAfter-Break" in text
    assert "a\\|b" in text


def test_hwp_reader_env_unset_fails_closed(monkeypatch):
    """HWP/HWPX extraction fails closed when the reviewed reader source is unset."""
    monkeypatch.delenv(document.HWP_READER_ENV, raising=False)
    with pytest.raises(
        document.DocumentReadError,
        match="reviewed hwp-mcp/rhwp reader is not configured",
    ):
        document.extract_review_document("docs/unconfigured.hwp", b"binary")


def test_hwp_reader_subprocess_os_error_fails_closed(monkeypatch):
    """An OSError starting the reviewed reader subprocess fails closed."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")

    def raise_os_error(*_args, **_kwargs):
        """Simulate a reviewed HWP reader subprocess that cannot start."""
        raise OSError("node executable not found")

    monkeypatch.setattr(document.subprocess, "run", raise_os_error)
    with pytest.raises(
        document.DocumentReadError,
        match="reviewed hwp-mcp/rhwp reader could not start",
    ):
        document.extract_review_document("docs/no-node.hwp", b"binary")


def test_hwp_reader_output_over_bounded_size_fails_closed(monkeypatch):
    """Reader stdout larger than the bounded text cap fails closed."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b"a" * (document.MAX_DOCUMENT_TEXT_BYTES + 1), stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(
        document.DocumentReadError,
        match="reviewed hwp-mcp/rhwp reader exceeded the bounded output",
    ):
        document.extract_review_document("docs/too-long.hwp", b"binary")


def test_hwp_reader_non_utf8_output_fails_closed(monkeypatch):
    """Non-UTF-8 reader stdout fails closed instead of producing replacement text."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b"\xff\xfe\xfa", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(
        document.DocumentReadError,
        match="reviewed hwp-mcp/rhwp reader returned non-UTF-8 text",
    ):
        document.extract_review_document("docs/bad-encoding.hwp", b"binary")


def test_hwp_reader_empty_output_fails_closed(monkeypatch):
    """Whitespace-only reader stdout fails closed as empty text."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b"   \n\t  ", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(
        document.DocumentReadError,
        match="reviewed hwp-mcp/rhwp reader returned empty text",
    ):
        document.extract_review_document("docs/blank.hwp", b"binary")


def test_bounded_text_truncates_multibyte_text_cleanly():
    """Truncation of multibyte text stays valid UTF-8 and reports omitted bytes."""
    text = "가" * ((document.MAX_DOCUMENT_TEXT_BYTES // 3) + 10)
    bounded = document._bounded_text(text)
    assert bounded != text
    assert "[document text truncated;" in bounded
    assert "bytes omitted]" in bounded
    prefix = bounded.split("\n[document text truncated;", 1)[0]
    assert len(prefix.encode("utf-8")) <= document.MAX_DOCUMENT_TEXT_BYTES


def test_main_entrypoint_prints_text_for_a_valid_docx(tmp_path, monkeypatch, capsys):
    """The __main__ CLI path prints extracted text and exits 0 for a valid DOCX."""
    docx_path = tmp_path / "good.docx"
    docx_path.write_bytes(_docx_bytes())
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(docx_path)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(Path("scripts/ci/noema_review_document.py")), run_name="__main__"
        )

    assert exc_info.value.code == 0
    assert "DOCX-REVIEW-MARKER" in capsys.readouterr().out


def test_main_entrypoint_exits_1_for_a_missing_file(tmp_path, monkeypatch, capsys):
    """The __main__ CLI path exits 1 and reports the error for a missing file."""
    missing_path = tmp_path / "missing.docx"
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(missing_path)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(Path("scripts/ci/noema_review_document.py")), run_name="__main__"
        )

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip() != ""


def test_fetch_file_content_at_ref_rejects_malformed_base64(monkeypatch):
    """A content response that is not valid base64 fails closed instead of decoding garbage."""
    monkeypatch.setattr(noema, "run", lambda _args, stdin=None: "not*valid*base64!!")

    with pytest.raises(RuntimeError, match="malformed base64"):
        noema.fetch_file_content_at_ref("owner/repo", "docs/review.docx", "head")
