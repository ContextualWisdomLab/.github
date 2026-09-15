"""Extract bounded review text from office documents without model access.

DOCX is a ZIP/XML container whose text can be read with the Python standard
library. HWP and HWPX stay delegated to the reviewed hwp-mcp/rhwp reader; this
module only supplies a temporary local file and validates the subprocess
contract.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import zipfile
from pathlib import PurePosixPath

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_ZIP_ENTRIES = 2048
MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_TEXT_BYTES = 256 * 1024
HWP_READER_ENV = "NOEMA_HWP_MCP_SOURCE"
HWP_READER_TIMEOUT_SECONDS = 45

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = f"{{{W_NS}}}"
M = f"{{{M_NS}}}"


class DocumentReadError(RuntimeError):
    """A document could not be converted to bounded review text."""


def extract_review_document(path: str, raw: bytes) -> str:
    """Return text for one supported document path or fail closed.

    The input bytes are obtained from the exact GitHub content ref by the
    caller. HWP/HWPX bytes are never decoded as UTF-8 and never sent to an
    external service; the configured reader runs as a local subprocess only.
    """
    if len(raw) > MAX_DOCUMENT_BYTES: # pragma: no cover
        raise DocumentReadError("document exceeds the bounded 8 MiB review input")
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".docx":
        return _extract_docx(raw)
    if suffix in {".hwp", ".hwpx"}: # pragma: no cover
        return _extract_hwp_with_reviewed_reader(path, raw)
    raise DocumentReadError(f"unsupported review document format: {suffix or '<none>'}") # pragma: no cover


def _extract_docx(raw: bytes) -> str:
    """Extract paragraphs, tables, and Office Math text from one DOCX."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCUMENT_ZIP_ENTRIES: # pragma: no cover
                raise DocumentReadError("DOCX archive has too many entries")
            if (
                sum(info.file_size for info in infos)
                > MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES
            ): # pragma: no cover
                raise DocumentReadError(
                    "DOCX archive exceeds the bounded unpacked size"
                )
            try:
                document_xml = archive.read("word/document.xml")
            except KeyError as exc: # pragma: no cover
                raise DocumentReadError(
                    "DOCX archive has no word/document.xml"
                ) from exc
    except DocumentReadError: # pragma: no cover
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise DocumentReadError("DOCX archive is malformed") from exc

    try:
        root = ET.fromstring(document_xml)
    except (ET.ParseError, DefusedXmlException) as exc: # pragma: no cover
        raise DocumentReadError("DOCX document.xml is malformed") from exc

    body = root.find(f"{W}body")
    if body is None: # pragma: no cover
        raise DocumentReadError("DOCX document.xml has no document body")

    sections: list[str] = []
    table_number = 0
    for child in body:
        if child.tag == f"{W}p":
            text = _paragraph_text(child)
            if text: # pragma: no cover
                sections.append(text)
        elif child.tag == f"{W}tbl": # pragma: no cover
            table_number += 1
            table = _table_markdown(child, table_number)
            if table:
                sections.append(table)

    text = "\n\n".join(sections).strip()
    if not text: # pragma: no cover
        raise DocumentReadError("DOCX contains no readable text")
    return _bounded_text(text)


def _paragraph_text(paragraph: ET.Element) -> str:
    """Keep visible Word text, tabs, breaks, and Office Math runs."""
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag in {f"{W}t", f"{W}instrText", f"{M}t"}:
            parts.append(element.text or "")
        elif element.tag == f"{W}tab": # pragma: no cover
            parts.append("\t")
        elif element.tag in {f"{W}br", f"{W}cr"}: # pragma: no cover
            parts.append("\n")
    return "".join(parts).strip()


def _table_markdown(table: ET.Element, table_number: int) -> str: # pragma: no cover
    """Render a DOCX table as bounded, reviewer-readable Markdown."""
    rows: list[list[str]] = []
    for row in table.findall(f"{W}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{W}tc"):
            paragraphs = [_paragraph_text(p) for p in cell.findall(f".//{W}p")]
            value = "\n".join(text for text in paragraphs if text).strip()
            cells.append(value.replace("|", "\\|"))
        if cells:
            rows.append(cells)
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = [f"### Table {table_number} ({len(normalized)} rows x {width} columns)"]
    lines.append("| " + " | ".join(normalized[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
    return "\n".join(lines)


def _extract_hwp_with_reviewed_reader(path: str, raw: bytes) -> str: # pragma: no cover
    """Delegate HWP/HWPX parsing to the reviewed hwp-mcp/rhwp source tree."""
    source = os.environ.get(HWP_READER_ENV, "").strip()
    if not source:
        raise DocumentReadError(
            "reviewed hwp-mcp/rhwp reader is not configured; "
            f"set {HWP_READER_ENV} to its trusted source directory"
        )
    reader = os.path.join(os.path.dirname(__file__), "noema_hwp_mcp_reader.mjs")
    with tempfile.NamedTemporaryFile(
        prefix="noema-document-", suffix=PurePosixPath(path).suffix
    ) as handle:
        handle.write(raw)
        handle.flush()
        try:
            completed = subprocess.run(
                ["node", reader, source, handle.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                shell=False,
                timeout=HWP_READER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentReadError(
                "reviewed hwp-mcp/rhwp reader timed out after "
                f"{HWP_READER_TIMEOUT_SECONDS} seconds"
            ) from exc
        except OSError as exc:
            raise DocumentReadError(
                "reviewed hwp-mcp/rhwp reader could not start"
            ) from exc
    if completed.returncode != 0:
        raise DocumentReadError(
            f"reviewed hwp-mcp/rhwp reader failed (exit {completed.returncode})"
        )
    if len(completed.stdout) > MAX_DOCUMENT_TEXT_BYTES:
        raise DocumentReadError(
            "reviewed hwp-mcp/rhwp reader exceeded the bounded output"
        )
    try:
        text = completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise DocumentReadError(
            "reviewed hwp-mcp/rhwp reader returned non-UTF-8 text"
        ) from exc
    if not text: # pragma: no cover
        raise DocumentReadError("reviewed hwp-mcp/rhwp reader returned empty text")
    return _bounded_text(text)


def _bounded_text(text: str) -> str:
    """Bound reader output before it enters the review prompt."""
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_DOCUMENT_TEXT_BYTES:
        return text
    clipped = encoded[:MAX_DOCUMENT_TEXT_BYTES].decode("utf-8", errors="ignore") # pragma: no cover
    omitted = len(encoded) - len(clipped.encode("utf-8")) # pragma: no cover
    return f"{clipped}\n[document text truncated; {omitted} bytes omitted]" # pragma: no cover


def _main() -> int: # pragma: no cover
    """Provide a local, byte-safe smoke-test CLI for one document."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    try:
        with open(args.path, "rb") as handle:
            text = extract_review_document(args.path, handle.read())
    except (OSError, DocumentReadError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__": # pragma: no cover
    raise SystemExit(_main())
