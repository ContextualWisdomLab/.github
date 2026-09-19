"""Regression tests for binary document input on the canonical Noema path."""

from __future__ import annotations

import base64
import io
import json
import os
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


def _zip_document(xml: str, extra: dict[str, str] | None = None) -> bytes:
    """Pack one synthetic DOCX XML document."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


def test_docx_reader_rejects_and_bounds_edge_documents(monkeypatch):
    """Size, archive, and body failures stay explicit reader errors."""
    monkeypatch.setattr(document, "MAX_DOCUMENT_BYTES", 4)
    with pytest.raises(document.DocumentReadError, match="8 MiB"):
        document.extract_review_document("docs/big.docx", b"12345")
    monkeypatch.setattr(document, "MAX_DOCUMENT_BYTES", 8 * 1024 * 1024)

    with pytest.raises(document.DocumentReadError, match="unsupported"):
        document.extract_review_document("docs/note.txt", b"hello")

    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_ENTRIES", 1)
    with pytest.raises(document.DocumentReadError, match="too many entries"):
        document.extract_review_document(
            "docs/many.docx",
            _zip_document("<w:document/>", {"word/extra.xml": "x"}),
        )
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_ENTRIES", 2048)

    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(document.DocumentReadError, match="unpacked size"):
        document.extract_review_document("docs/huge.docx", _docx_bytes())
    monkeypatch.setattr(
        document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 64 * 1024 * 1024
    )

    empty_zip = io.BytesIO()
    with zipfile.ZipFile(empty_zip, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    with pytest.raises(document.DocumentReadError, match="no word/document.xml"):
        document.extract_review_document("docs/noxml.docx", empty_zip.getvalue())

    no_body = _zip_document(
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
    )
    with pytest.raises(document.DocumentReadError, match="no document body"):
        document.extract_review_document("docs/nobody.docx", no_body)

    mixed = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p></w:p>
    <w:sectPr/>
    <w:tbl><w:tr></w:tr></w:tbl>
    <w:p><w:r><w:tab/><w:br/><w:t>EDGE</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    assert "EDGE" in document.extract_review_document("docs/edge.docx", _zip_document(mixed))

    blank = """<?xml version="1.0"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p></w:p></w:body>
</w:document>"""
    with pytest.raises(document.DocumentReadError, match="no readable text"):
        document.extract_review_document("docs/blank.docx", _zip_document(blank))

    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 2)
    clipped = document.extract_review_document("docs/edge.docx", _zip_document(mixed))
    assert "truncated" in clipped


def test_hwp_reader_rejects_missing_runtime_and_bad_output(monkeypatch):
    """HWP failures before and after the subprocess stay fail-closed."""
    monkeypatch.delenv(document.HWP_READER_ENV, raising=False)
    with pytest.raises(document.DocumentReadError, match="not configured"):
        document.extract_review_document("docs/a.hwp", b"x")

    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")

    def cannot_start(*_args, **_kwargs):
        raise OSError("no node")

    monkeypatch.setattr(document.subprocess, "run", cannot_start)
    with pytest.raises(document.DocumentReadError, match="could not start"):
        document.extract_review_document("docs/a.hwp", b"x")

    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 1)
    oversized = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b"abcdef", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *_args, **_kwargs: oversized)
    with pytest.raises(document.DocumentReadError, match="bounded output"):
        document.extract_review_document("docs/a.hwp", b"x")

    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 256 * 1024)
    non_utf8 = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b"\xff", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *_args, **_kwargs: non_utf8)
    with pytest.raises(document.DocumentReadError, match="non-UTF-8"):
        document.extract_review_document("docs/a.hwp", b"x")

    empty = document.subprocess.CompletedProcess(
        ["node"], 0, stdout=b" \n", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *_args, **_kwargs: empty)
    with pytest.raises(document.DocumentReadError, match="empty text"):
        document.extract_review_document("docs/a.hwp", b"x")


def test_document_cli_prints_text_and_read_errors(monkeypatch, tmp_path, capsys):
    """The local smoke-test CLI reports one document or its read error."""
    missing = tmp_path / "missing.docx"
    monkeypatch.setattr(sys, "argv", ["noema_review_document", str(missing)])
    assert document._main() == 1
    assert capsys.readouterr().err

    good = tmp_path / "ok.docx"
    good.write_bytes(_docx_bytes())
    monkeypatch.setattr(sys, "argv", ["noema_review_document", str(good)])
    assert document._main() == 0
    assert "DOCX-REVIEW-MARKER" in capsys.readouterr().out
