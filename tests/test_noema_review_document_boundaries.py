"""Exercise document-reader failure boundaries used by protected review."""

from __future__ import annotations

import io
import runpy
import sys
import zipfile
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.ci import noema_review_document as document


def _docx(xml: str | None, *, extra_entries: int = 0) -> bytes:
    """Build a small DOCX archive with optional missing document XML."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        if xml is not None:
            archive.writestr("word/document.xml", xml)
        for index in range(extra_entries):
            archive.writestr(f"extra-{index}", "x")
    return output.getvalue()


def _body(content: str) -> str:
    """Wrap Word body content in the namespace expected by the reader."""
    return (
        f'<w:document xmlns:w="{document.W_NS}">'
        f"<w:body>{content}</w:body></w:document>"
    )


def test_document_input_limits_and_unsupported_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject oversized, unsupported, and unconfigured reader inputs."""
    monkeypatch.setattr(document, "MAX_DOCUMENT_BYTES", 2)
    with pytest.raises(document.DocumentReadError, match="8 MiB"):
        document.extract_review_document("a.docx", b"long")
    with pytest.raises(document.DocumentReadError, match="unsupported"):
        document.extract_review_document("a.pdf", b"ok")
    monkeypatch.delenv(document.HWP_READER_ENV, raising=False)
    with pytest.raises(document.DocumentReadError, match="not configured"):
        document.extract_review_document("a.hwp", b"ok")


def test_docx_archive_and_xml_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject partial archives and XML without visible document content."""
    valid = _docx(_body("<w:p><w:r><w:t>ok</w:t></w:r></w:p>"))
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_ENTRIES", 0)
    with pytest.raises(document.DocumentReadError, match="too many entries"):
        document.extract_review_document("a.docx", valid)
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_ENTRIES", 2048)
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(document.DocumentReadError, match="unpacked size"):
        document.extract_review_document("a.docx", valid)
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 64 * 1024 * 1024)
    cases = (
        (_docx(None, extra_entries=1), "no word/document.xml"),
        (_docx("<broken"), "malformed"),
        (_docx(f'<w:document xmlns:w="{document.W_NS}"/>'), "no document body"),
        (_docx(_body("<w:p/>")), "no readable text"),
    )
    for payload, message in cases:
        with pytest.raises(document.DocumentReadError, match=message):
            document.extract_review_document("a.docx", payload)


def test_docx_visible_controls_and_uneven_table() -> None:
    """Keep tabs, line breaks, and uneven table cells in reviewer text."""
    xml = _body(
        "<w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t><w:cr/></w:r></w:p>"
        "<w:tbl><w:tr/><w:tr><w:tc><w:p><w:r><w:t>X|Y</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p/></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Z</w:t>"
        "</w:r></w:p></w:tc></w:tr></w:tbl><w:tbl><w:tr/></w:tbl>"
        "<w:unknown/>"
    )
    text = document.extract_review_document("a.docx", _docx(xml))
    assert "A\tB\nC" in text
    assert "X\\|Y" in text
    assert "| Z |  |" in text
    assert "### Table 1 (2 rows x 2 columns)" in text
    assert "Table 2" not in text


def test_hwp_reader_rejects_process_and_output_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep parser failures and untrusted output out of the review prompt."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/reviewed/source")

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise OSError("private process detail")

    monkeypatch.setattr(document.subprocess, "run", unavailable)
    with pytest.raises(document.DocumentReadError, match="could not start"):
        document.extract_review_document("a.hwpx", b"data")

    for stdout, message in ((b"abcd", "bounded output"), (b"\xff", "non-UTF-8"), (b"  ", "empty text")):
        monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 3)
        completed = CompletedProcess(["node"], 0, stdout, b"")
        monkeypatch.setattr(
            document.subprocess,
            "run",
            lambda *_args, **_kwargs: completed,
        )
        with pytest.raises(document.DocumentReadError, match=message):
            document.extract_review_document("a.hwpx", b"data")


def test_document_text_truncation_and_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Bound UTF-8 output and preserve a useful local CLI failure exit."""
    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 4)
    assert document._bounded_text("ééé").startswith("éé\n[document text truncated;")
    assert document._bounded_text("ok") == "ok"

    path = tmp_path / "review.docx"
    path.write_bytes(_docx(_body("<w:p><w:r><w:t>ok</w:t></w:r></w:p>")))
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(path)])
    assert document._main() == 0
    assert "ok" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(path.with_name("missing.docx"))])
    assert document._main() == 1
    assert capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(path)])
    with pytest.raises(SystemExit) as exit_status:
        runpy.run_path(str(Path(document.__file__)), run_name="__main__")
    assert exit_status.value.code == 0
