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


def _docx_archive(entries: dict[str, str | bytes]) -> bytes:
    """Build a small DOCX-like ZIP from explicit member contents."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for member_name, member_body in entries.items():
            archive.writestr(member_name, member_body)
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


def test_document_reader_rejects_unsupported_and_oversized_inputs(monkeypatch):
    """The public reader enforces its format and compressed-input bounds first."""
    with pytest.raises(document.DocumentReadError, match=r"unsupported.*\.txt"):
        document.extract_review_document("docs/review.txt", b"plain text")

    monkeypatch.setattr(document, "MAX_DOCUMENT_BYTES", 3)
    with pytest.raises(document.DocumentReadError, match="exceeds.*8 MiB"):
        document.extract_review_document("docs/review.docx", b"1234")


def test_docx_archive_and_xml_boundaries_fail_closed(monkeypatch):
    """Malformed DOCX container structures expose bounded stable errors."""
    valid_xml = (
        f'<w:document xmlns:w="{document.W_NS}"><w:body>'
        "<w:p><w:r><w:t>text</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    archive = _docx_archive({"word/document.xml": valid_xml})

    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_ENTRIES", 0)
    with pytest.raises(document.DocumentReadError, match="too many entries"):
        document.extract_review_document("docs/review.docx", archive)
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_ENTRIES", 2048)

    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 1)
    with pytest.raises(document.DocumentReadError, match="bounded unpacked size"):
        document.extract_review_document("docs/review.docx", archive)
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 64 * 1024 * 1024)

    missing_xml = _docx_archive({"word/styles.xml": "<styles/>"})
    with pytest.raises(document.DocumentReadError, match="no word/document.xml"):
        document.extract_review_document("docs/review.docx", missing_xml)

    malformed_xml = _docx_archive({"word/document.xml": "<not-closed>"})
    with pytest.raises(document.DocumentReadError, match="document.xml is malformed"):
        document.extract_review_document("docs/review.docx", malformed_xml)

    no_body = _docx_archive(
        {
            "word/document.xml": (
                f'<w:document xmlns:w="{document.W_NS}"></w:document>'
            )
        }
    )
    with pytest.raises(document.DocumentReadError, match="no document body"):
        document.extract_review_document("docs/review.docx", no_body)

    empty_body = _docx_archive(
        {
            "word/document.xml": (
                f'<w:document xmlns:w="{document.W_NS}"><w:body>'
                "<w:p/><w:tbl/><w:sectPr/>"
                "</w:body></w:document>"
            )
        }
    )
    with pytest.raises(document.DocumentReadError, match="no readable text"):
        document.extract_review_document("docs/review.docx", empty_body)


def test_docx_visible_controls_and_ragged_tables_are_preserved():
    """Visible Word controls and reviewer-safe table structure survive extraction."""
    xml = f"""<w:document xmlns:w="{document.W_NS}">
  <w:body>
    <w:p><w:instrText>field</w:instrText><w:tab/><w:t>A</w:t><w:br/><w:t>B</w:t><w:cr/><w:t>C</w:t></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:t>left|pipe</w:t></w:p></w:tc><w:tc><w:p/></w:tc></w:tr>
      <w:tr/>
      <w:tr><w:tc><w:p><w:t>short</w:t></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    text = document.extract_review_document(
        "docs/controls.docx", _docx_archive({"word/document.xml": xml})
    )

    assert "field\tA\nB\nC" in text
    assert "### Table 1 (2 rows x 2 columns)" in text
    assert "| left\\|pipe |  |" in text
    assert "| short |  |" in text


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


def test_hwp_reader_rejects_configuration_process_and_output_failures(monkeypatch):
    """Every local HWP adapter boundary fails closed without leaking output."""
    monkeypatch.delenv(document.HWP_READER_ENV, raising=False)
    with pytest.raises(document.DocumentReadError, match="is not configured"):
        document.extract_review_document("docs/review.hwp", b"binary")

    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")

    def cannot_start(*_args, **_kwargs):
        raise OSError("node unavailable")

    monkeypatch.setattr(document.subprocess, "run", cannot_start)
    with pytest.raises(document.DocumentReadError, match="could not start"):
        document.extract_review_document("docs/review.hwp", b"binary")

    def completed(stdout: bytes):
        return document.subprocess.CompletedProcess(
            ["node"], 0, stdout=stdout, stderr=b"private adapter details"
        )

    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 3)
    monkeypatch.setattr(document.subprocess, "run", lambda *_a, **_k: completed(b"four"))
    with pytest.raises(document.DocumentReadError, match="bounded output"):
        document.extract_review_document("docs/review.hwpx", b"binary")

    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 256 * 1024)
    monkeypatch.setattr(document.subprocess, "run", lambda *_a, **_k: completed(b"\xff"))
    with pytest.raises(document.DocumentReadError, match="non-UTF-8"):
        document.extract_review_document("docs/review.hwpx", b"binary")

    monkeypatch.setattr(document.subprocess, "run", lambda *_a, **_k: completed(b" \n"))
    with pytest.raises(document.DocumentReadError, match="empty text"):
        document.extract_review_document("docs/review.hwpx", b"binary")


def test_document_text_bound_preserves_utf8_boundary_and_reports_omission(monkeypatch):
    """The public DOCX path never emits a partial UTF-8 code point."""
    xml = (
        f'<w:document xmlns:w="{document.W_NS}"><w:body>'
        "<w:p><w:r><w:t>ééé</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    monkeypatch.setattr(document, "MAX_DOCUMENT_TEXT_BYTES", 5)
    assert document.extract_review_document(
        "docs/multibyte.docx", _docx_archive({"word/document.xml": xml})
    ) == (
        "éé\n[document text truncated; 2 bytes omitted]"
    )


def test_document_reader_cli_success_failure_and_entrypoint(
    tmp_path, monkeypatch, capsys
):
    """The byte-safe local CLI returns and propagates stable process statuses."""
    docx_path = tmp_path / "review.docx"
    docx_path.write_bytes(_docx_bytes())

    monkeypatch.setattr(sys, "argv", [document.__file__, str(docx_path)])
    assert document._main() == 0
    assert "DOCX-REVIEW-MARKER" in capsys.readouterr().out

    missing_path = tmp_path / "missing.docx"
    monkeypatch.setattr(sys, "argv", [document.__file__, str(missing_path)])
    assert document._main() == 1
    assert str(missing_path) in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", [document.__file__, str(docx_path)])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(document.__file__, run_name="__main__")
    assert raised.value.code == 0


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
