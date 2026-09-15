import pytest
from scripts.ci.noema_review_document import (
    extract_review_document,
    DocumentReadError,
    _bounded_text,
    _extract_docx,
    _extract_hwp_with_reviewed_reader,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_TEXT_BYTES,
)
import zipfile
import io
import os
import subprocess
from unittest import mock

def test_extract_review_document_too_large():
    with pytest.raises(DocumentReadError, match="document exceeds"):
        extract_review_document("test.docx", b"a" * (MAX_DOCUMENT_BYTES + 1))

def test_extract_review_document_unsupported():
    with pytest.raises(DocumentReadError, match="unsupported review document format"):
        extract_review_document("test.txt", b"abc")

def test_extract_docx_malformed():
    with pytest.raises(DocumentReadError, match="DOCX archive is malformed"):
        _extract_docx(b"not a zip")

def test_extract_docx_missing_document_xml():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/other.xml", "test")
    with pytest.raises(DocumentReadError, match="DOCX archive has no word/document.xml"):
        _extract_docx(buf.getvalue())

def test_extract_docx_malformed_xml():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<invalid")
    with pytest.raises(DocumentReadError, match="DOCX document.xml is malformed"):
        _extract_docx(buf.getvalue())

def test_extract_docx_no_body():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<root></root>")
    with pytest.raises(DocumentReadError, match="DOCX document.xml has no document body"):
        _extract_docx(buf.getvalue())

def test_extract_docx_no_text():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p></w:p></w:body></root>')
    with pytest.raises(DocumentReadError, match="DOCX contains no readable text"):
        _extract_docx(buf.getvalue())

def test_extract_docx_success():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>Hello</w:t></w:p></w:body></root>')
    res = _extract_docx(buf.getvalue())
    assert res == "Hello"

def test_extract_docx_table():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc><w:p><w:t>A1</w:t></w:p></w:tc><w:tc><w:p><w:t>B1</w:t></w:p></w:tc></w:tr></w:tbl></w:body></root>')
    res = _extract_docx(buf.getvalue())
    assert "### Table 1" in res
    assert "| A1 | B1 |" in res

def test_extract_hwp_no_reader():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": ""}):
        with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader is not configured"):
            _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_timeout():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["node"], 45)):
            with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader timed out"):
                _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_oserror():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", side_effect=OSError("Not found")):
            with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader could not start"):
                _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_failed():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)):
            with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader failed"):
                _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_exceeded():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"a" * (MAX_DOCUMENT_TEXT_BYTES + 1))):
            with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader exceeded the bounded output"):
                _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_decode_error():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"\xff")):
            with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader returned non-UTF-8 text"):
                _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_empty():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"  ")):
            with pytest.raises(DocumentReadError, match="reviewed hwp-mcp/rhwp reader returned empty text"):
                _extract_hwp_with_reviewed_reader("test.hwp", b"abc")

def test_extract_hwp_success():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"success text")):
            res = _extract_hwp_with_reviewed_reader("test.hwp", b"abc")
            assert res == "success text"

def test_bounded_text():
    short_text = "abc"
    assert _bounded_text(short_text) == short_text
    long_text = "a" * (MAX_DOCUMENT_TEXT_BYTES + 10)
    res = _bounded_text(long_text)
    assert "[document text truncated;" in res

def test_main_cli(monkeypatch):
    import sys
    with mock.patch("sys.argv", ["script", "dummy.docx"]):
        with mock.patch("builtins.open", mock.mock_open(read_data=b"dummy")):
            with mock.patch("scripts.ci.noema_review_document.extract_review_document", return_value="ok"):
                from scripts.ci.noema_review_document import _main
                assert _main() == 0

def test_main_cli_error(monkeypatch):
    import sys
    with mock.patch("sys.argv", ["script", "dummy.docx"]):
        with mock.patch("builtins.open", side_effect=OSError("test err")):
            from scripts.ci.noema_review_document import _main
            assert _main() == 1

def test_extract_docx_too_many_entries():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(2049):
            z.writestr(f"file{i}.txt", "data")
    with pytest.raises(DocumentReadError, match="DOCX archive has too many entries"):
        _extract_docx(buf.getvalue())

def test_extract_docx_too_large_uncompressed():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("large.txt", b"a" * (64 * 1024 * 1024 + 1))
    with pytest.raises(DocumentReadError, match="DOCX archive exceeds the bounded unpacked size"):
        _extract_docx(buf.getvalue())

def test_extract_docx_paragraph_tab():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>A</w:t><w:tab/><w:t>B</w:t></w:p></w:body></root>')
    res = _extract_docx(buf.getvalue())
    assert res == "A\tB"

def test_extract_docx_paragraph_br():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>A</w:t><w:br/><w:t>B</w:t></w:p></w:body></root>')
    res = _extract_docx(buf.getvalue())
    assert res == "A\nB"

def test_extract_review_document_hwp():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"hwp text")):
            res = extract_review_document("test.hwp", b"abc")
            assert res == "hwp text"

def test_extract_review_document_hwpx():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"hwpx text")):
            res = extract_review_document("test.hwpx", b"abc")
            assert res == "hwpx text"


def test_extract_docx_table_empty():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl></w:tbl></w:body></root>')
    with pytest.raises(DocumentReadError, match="DOCX contains no readable text"):
        _extract_docx(buf.getvalue())

def test_extract_docx_table_empty_row():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr></w:tr></w:tbl></w:body></root>')
    with pytest.raises(DocumentReadError, match="DOCX contains no readable text"):
        _extract_docx(buf.getvalue())

def test_extract_docx_table_empty_cell():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc></w:tc></w:tr></w:tbl></w:body></root>')
    res = _extract_docx(buf.getvalue())
    assert "Table" in res
def test_main_cli_success(monkeypatch):
    import sys
    with mock.patch("sys.argv", ["script", "dummy.docx"]):
        with mock.patch("builtins.open", mock.mock_open(read_data=b"dummy")):
            with mock.patch("scripts.ci.noema_review_document.extract_review_document", return_value="ok"):
                from scripts.ci.noema_review_document import _main
                assert _main() == 0


def test_extract_docx_badzip():
    with pytest.raises(DocumentReadError, match="DOCX archive is malformed"):
        _extract_docx(b"PK\x03\x04123")

def test_extract_review_document_large_docx():
    # just under max
    pass


def test_extract_docx_not_zipfile_empty():
    with pytest.raises(DocumentReadError, match="DOCX archive is malformed"):
        _extract_docx(b"")

def test_extract_docx_none_suffix():
    with pytest.raises(DocumentReadError, match="unsupported review document format: <none>"):
        extract_review_document("test", b"abc")


def test_extract_docx_parse_error():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<root>&invalid;</root>")
    with pytest.raises(DocumentReadError, match="DOCX document.xml is malformed"):
        _extract_docx(buf.getvalue())
def test_main_cli_import():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "scripts/ci/noema_review_document.py", "dummy.docx"], capture_output=True)
    assert out.returncode == 1
def test_extract_docx_raise_document_read_error():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(2049):
            z.writestr(f"file{i}.txt", "data")
    with pytest.raises(DocumentReadError):
        _extract_docx(buf.getvalue())
def test_extract_docx_value_error_in_zip():
    with mock.patch("zipfile.ZipFile", side_effect=ValueError):
        with pytest.raises(DocumentReadError, match="DOCX archive is malformed"):
            _extract_docx(b"invalid")
def test_extract_review_document_hwp_direct():
    with mock.patch.dict(os.environ, {"NOEMA_HWP_MCP_SOURCE": "dummy"}):
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout=b"hwp text")):
            res = extract_review_document("test.hwp", b"abc")
            assert res == "hwp text"

def test_extract_review_document_docx_direct():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:t>Hello</w:t></w:p></w:body></root>')
    res = extract_review_document("test.docx", buf.getvalue())
    assert res == "Hello"

def test_extract_review_document_none_direct():
    with pytest.raises(DocumentReadError):
        extract_review_document("test", b"abc")
def test_extract_docx_unsupported_tag():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:other></w:other><w:p><w:t>Hello</w:t></w:p></w:body></root>')
    res = _extract_docx(buf.getvalue())
    assert res == "Hello"

def test_if_name_main():
    with pytest.raises(SystemExit):
        import runpy
        with mock.patch("sys.argv", ["script", "dummy"]):
            with mock.patch("scripts.ci.noema_review_document._main", return_value=0):
                try:
                    runpy.run_module('scripts.ci.noema_review_document', run_name='__main__')
                except SystemExit:
                    raise
