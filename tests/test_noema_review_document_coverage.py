"""Every fail-closed branch of the Noema document reader is exercised for real."""

from __future__ import annotations

import io
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.ci import noema_review_document as nrd
from scripts.ci import noema_review_gate as gate

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _zip(members: dict[str, str]) -> bytes:
    """Build an in-memory ZIP."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _docx(body: str) -> bytes:
    """Build a DOCX whose body XML is ``body``."""
    return _zip({"word/document.xml": f"<w:document {W}>{body}</w:document>"})


def test_docx_keeps_tabs_breaks_and_skips_empty_paragraphs_tables_and_other_children() -> None:
    """Tabs and breaks survive; empty paragraphs, empty tables and sectPr are skipped."""
    body = (
        "<w:body>"
        "<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t><w:br/><w:t>c</w:t></w:r></w:p>"
        "<w:p/>"
        "<w:tbl><w:tr/></w:tbl>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>x|y</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc><w:tc/></w:tr></w:tbl>"
        "<w:sectPr/>"
        "</w:body>"
    )
    text = nrd.extract_review_document("doc.docx", _docx(body))
    assert text.startswith("a\tb\nc")
    assert "### Table 2 (2 rows x 2 columns)" in text and "x\\|y" in text
    assert "Table 1" not in text


@pytest.mark.parametrize(
    ("path", "raw", "message"),
    (
        ("a.txt", b"x", "unsupported review document format: .txt"),
        ("noext", b"x", "unsupported review document format: <none>"),
        ("a.docx", b"not a zip", "DOCX archive is malformed"),
        ("a.docx", _zip({"other.xml": "<x/>"}), "has no word/document.xml"),
        ("a.docx", _docx("<w:notbody/>"), "has no document body"),
        ("a.docx", _docx("<w:body><w:p/></w:body>"), "contains no readable text"),
        ("a.docx", _zip({"word/document.xml": "<unclosed>"}), "document.xml is malformed"),
    ),
)
def test_malformed_or_unsupported_documents_fail_closed(path: str, raw: bytes, message: str) -> None:
    """Unsupported, malformed, bodyless or empty documents raise instead of passing."""
    with pytest.raises(nrd.DocumentReadError, match=message):
        nrd.extract_review_document(path, raw)


def test_size_entry_and_expansion_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Input size, archive entries and unpacked size are all bounded."""
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_BYTES", 4)
    with pytest.raises(nrd.DocumentReadError, match="exceeds the bounded 8 MiB"):
        nrd.extract_review_document("a.docx", b"12345")
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_BYTES", 10**9)
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_ZIP_ENTRIES", 0)
    with pytest.raises(nrd.DocumentReadError, match="too many entries"):
        nrd.extract_review_document("a.docx", _docx("<w:body/>"))
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_ZIP_ENTRIES", 10)
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(nrd.DocumentReadError, match="bounded unpacked size"):
        nrd.extract_review_document("a.docx", _docx("<w:body/>"))


def test_long_text_is_truncated_on_utf8_bytes_with_a_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text over the byte bound is cut on a UTF-8 boundary and says how much was omitted."""
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_TEXT_BYTES", 7)
    text = nrd.extract_review_document("k.docx", _docx("<w:body><w:p><w:r><w:t>가나다</w:t></w:r></w:p></w:body>"))
    assert text == "가나\n[document text truncated; 3 bytes omitted]"


def _fake_reader(monkeypatch: pytest.MonkeyPatch, *, stdout: bytes = b"ok", returncode: int = 0, error: Exception | None = None) -> None:
    """Configure the reviewed reader and replace its subprocess with a canned result."""
    monkeypatch.setenv(nrd.HWP_READER_ENV, "/trusted/hwp-mcp")

    def fake_run(argv, **kwargs):
        """Return the canned reader result without launching node."""
        assert kwargs["shell"] is False and argv[0] == "node"
        if error is not None:
            raise error
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=b"")

    monkeypatch.setattr(nrd.subprocess, "run", fake_run)


def test_hwp_reader_failures_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unconfigured, unstartable, oversized, non-UTF-8, empty and failing readers all raise."""
    monkeypatch.delenv(nrd.HWP_READER_ENV, raising=False)
    with pytest.raises(nrd.DocumentReadError, match="reader is not configured"):
        nrd.extract_review_document("a.hwpx", b"PK")
    cases = (
        ({"error": OSError("no node")}, "could not start"),
        ({"returncode": 3}, r"failed \(exit 3\)"),
        ({"stdout": b"\xff\xfe"}, "non-UTF-8"),
        ({"stdout": b"   "}, "returned empty text"),
    )
    for kwargs, message in cases:
        _fake_reader(monkeypatch, **kwargs)
        with pytest.raises(nrd.DocumentReadError, match=message):
            nrd.extract_review_document("a.hwp", b"HWP")
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_TEXT_BYTES", 2)
    _fake_reader(monkeypatch, stdout=b"too long")
    with pytest.raises(nrd.DocumentReadError, match="exceeded the bounded output"):
        nrd.extract_review_document("a.hwpx", b"PK")
    monkeypatch.setattr(nrd, "MAX_DOCUMENT_TEXT_BYTES", 256 * 1024)
    _fake_reader(monkeypatch, stdout="한글 본문".encode())
    assert nrd.extract_review_document("a.hwpx", b"PK") == "한글 본문"


def test_cli_prints_text_or_reports_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The smoke-test CLI prints extracted text and exits 1 on unreadable input."""
    good = tmp_path / "good.docx"
    good.write_bytes(_docx("<w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body>"))
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(good)])
    assert nrd._main() == 0
    assert capsys.readouterr().out.strip() == "hello"
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(tmp_path / "missing.docx")])
    assert nrd._main() == 1
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(good)])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(nrd.__file__, run_name="__main__")
    assert exited.value.code == 0


def test_gate_rejects_malformed_base64_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """A content API payload that is not base64 fails closed in the gate."""
    monkeypatch.setattr(gate, "run", lambda *_a, **_k: "!!not-base64!!")
    with pytest.raises(RuntimeError, match="malformed base64"):
        gate.fetch_file_content_at_ref("o/r", "notes.md", "c" * 40)
