"""Extract bounded review text and figures from office documents.

DOCX is a ZIP/XML container whose text and embedded media can be read with the
Python standard library. HWP and HWPX stay delegated to the reviewed
hwp-mcp/rhwp reader for text; when those archives also contain embedded media
this module fails closed unless the media can be attached as multimodal parts
(see ContextualWisdomLab/.github#2280). Research originals and participant
materials are never used as fixtures — synthetic archives only.
"""

from __future__ import annotations

import base64
import io
import os
import posixpath
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException


MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_ZIP_ENTRIES = 2048
MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_TEXT_BYTES = 256 * 1024
MAX_DOCUMENT_IMAGES = 8
MAX_DOCUMENT_IMAGE_BYTES = int(1.5 * 1024 * 1024)
HWP_READER_ENV = "NOEMA_HWP_MCP_SOURCE"
HWP_READER_TIMEOUT_SECONDS = 45

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
W = f"{{{W_NS}}}"
R = f"{{{R_NS}}}"
A = f"{{{A_NS}}}"
M = f"{{{M_NS}}}"

_IMAGE_SUFFIX_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


class DocumentReadError(RuntimeError):
    """A document could not be converted to bounded review evidence."""


@dataclass(frozen=True)
class DocumentImage:
    """One embedded figure extracted for multimodal review attachment."""

    path: str
    media_path: str
    mime_type: str
    data: bytes
    locator: str

    def to_multimodal_parts(self) -> list[dict[str, Any]]:
        """Return OpenAI-style text locator + image_url content parts."""
        encoded = base64.standard_b64encode(self.data).decode("ascii")
        return [
            {
                "type": "text",
                "text": (
                    f"[document figure] path={self.path} media={self.media_path} "
                    f"locator={self.locator} mime={self.mime_type}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{self.mime_type};base64,{encoded}"},
            },
        ]


@dataclass
class DocumentExtraction:
    """Bounded text plus figures for one review document."""

    path: str
    text: str
    images: list[DocumentImage] = field(default_factory=list)
    media_declared: int = 0

    def multimodal_parts(self) -> list[dict[str, Any]]:
        """Flatten figure attachments for the reviewer request envelope."""
        parts: list[dict[str, Any]] = []
        for image in self.images:
            parts.extend(image.to_multimodal_parts())
        return parts

    def ensure_figures_attached(self) -> None:
        """Fail closed when the archive declared media that was not attached."""
        if self.media_declared and not self.images:
            raise DocumentReadError(
                f"{self.path}: document declares {self.media_declared} embedded "
                "media entr(y/ies) but no image parts were attached; refusing "
                "text-only success (ContextualWisdomLab/.github#2280)"
            )
        if self.media_declared and len(self.images) < self.media_declared:
            raise DocumentReadError(
                f"{self.path}: attached {len(self.images)} image part(s) but "
                f"archive declared {self.media_declared}; refusing partial "
                "figure coverage as success"
            )


def extract_review_document(path: str, raw: bytes) -> str:
    """Return text for one supported document path or fail closed.

    When the document contains embedded figures, extraction fails closed unless
    those figures are also represented as multimodal parts via
    :func:`extract_review_document_bundle` — this text-only helper therefore
    rejects figure-bearing archives so omission cannot look like success.
    """
    bundle = extract_review_document_bundle(path, raw)
    if bundle.media_declared or bundle.images:
        raise DocumentReadError(
            f"{path}: embedded figures require multimodal attachment; use "
            "extract_review_document_bundle / reviewer multimodal envelope "
            "(ContextualWisdomLab/.github#2280)"
        )
    return bundle.text


def extract_review_document_bundle(path: str, raw: bytes) -> DocumentExtraction:
    """Return text and figure parts for one supported document path."""
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise DocumentReadError("document exceeds the bounded 8 MiB review input")
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".docx":
        extraction = _extract_docx_bundle(path, raw)
    elif suffix in {".hwp", ".hwpx"}:
        extraction = _extract_hwp_bundle(path, raw)
    else:
        raise DocumentReadError(f"unsupported review document format: {suffix or '<none>'}")
    extraction.ensure_figures_attached()
    return extraction


def _extract_docx_bundle(path: str, raw: bytes) -> DocumentExtraction:
    """Extract paragraphs, tables, Office Math, and embedded DOCX media."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCUMENT_ZIP_ENTRIES:
                raise DocumentReadError("DOCX archive has too many entries")
            if (
                sum(info.file_size for info in infos)
                > MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES
            ):
                raise DocumentReadError(
                    "DOCX archive exceeds the bounded unpacked size"
                )
            try:
                document_xml = archive.read("word/document.xml")
            except KeyError as exc:
                raise DocumentReadError(
                    "DOCX archive has no word/document.xml"
                ) from exc
            try:
                root = ET.fromstring(document_xml)
            except (ET.ParseError, DefusedXmlException) as exc:
                raise DocumentReadError("DOCX document.xml is malformed") from exc

            body = root.find(f"{W}body")
            if body is None:
                raise DocumentReadError("DOCX document.xml has no document body")
            media_names, locators = _docx_image_references(archive, body)
            images = _docx_images_from_archive(
                path, archive, media_names, locators=locators
            )
    except DocumentReadError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise DocumentReadError("DOCX archive is malformed") from exc

    sections: list[str] = [f"[document text] path={path}"]
    table_number = 0
    for child in body:
        if child.tag == f"{W}p":
            text = _paragraph_text(child)
            if text:
                sections.append(text)
        elif child.tag == f"{W}tbl":
            table_number += 1
            table = _table_markdown(child, table_number)
            if table:
                sections.append(table)

    text = "\n\n".join(sections).strip()
    if not text or text == f"[document text] path={path}":
        if not images:
            raise DocumentReadError("DOCX contains no readable text")
        text = f"[document text] path={path}\n[body empty; figures attached separately]"
    return DocumentExtraction(
        path=path,
        text=_bounded_text(text),
        images=images,
        media_declared=len(media_names),
    )


def _docx_image_references(
    archive: zipfile.ZipFile,
    body: ET.Element,
) -> tuple[list[str], list[str]]:
    """Resolve main-document image relationships in source order."""
    blips = list(body.iter(f"{A}blip"))
    if not blips:
        return [], []
    try:
        relationships_xml = archive.read("word/_rels/document.xml.rels")
    except KeyError as exc:
        raise DocumentReadError(
            "DOCX body image has an unresolved relationship"
        ) from exc
    try:
        relationships_root = ET.fromstring(relationships_xml)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise DocumentReadError("DOCX document relationships are malformed") from exc

    relationship_targets: dict[str, str] = {}
    relationship_ids: set[str] = set()
    for relationship in relationships_root.findall(f"{{{PKG_REL_NS}}}Relationship"):
        relationship_id = relationship.attrib.get("Id")
        target = relationship.attrib.get("Target")
        relationship_type = relationship.attrib.get("Type", "")
        if relationship_id and relationship_id in relationship_ids:
            raise DocumentReadError(
                f"DOCX has duplicate relationship ID {relationship_id}"
            )
        if relationship_id:
            relationship_ids.add(relationship_id)
        if (
            not relationship_id
            or not target
            or not relationship_type.endswith("/image")
            or relationship.attrib.get("TargetMode", "").casefold() == "external"
        ):
            continue
        target_path = PurePosixPath(target)
        if (
            target_path.is_absolute()
            or ".." in target_path.parts
            or "\\" in target
            or "?" in target
            or "#" in target
        ):
            raise DocumentReadError(
                f"DOCX image relationship {relationship_id} targets "
                "outside word/media"
            )
        media_path = posixpath.normpath(posixpath.join("word", target))
        if not media_path.startswith("word/media/"):
            raise DocumentReadError(
                f"DOCX image relationship {relationship_id} targets "
                "outside word/media"
            )
        relationship_targets[relationship_id] = media_path

    media_names: list[str] = []
    locators: list[str] = []
    for index, blip in enumerate(blips, start=1):
        relationship_id = blip.attrib.get(f"{R}embed")
        media_path = relationship_targets.get(relationship_id or "")
        if media_path is None:
            raise DocumentReadError(
                f"DOCX body image has unresolved relationship "
                f"{relationship_id or '<missing>'}"
            )
        media_names.append(media_path)
        locators.append(
            f"document-body-blip-{index}:{relationship_id}->{media_path}"
        )
    return media_names, locators


def _docx_images_from_archive(
    path: str,
    archive: zipfile.ZipFile,
    media_names: list[str],
    *,
    locators: list[str] | None = None,
) -> list[DocumentImage]:
    """Load bounded DOCX media entries as multimodal figure parts."""
    return _images_from_archive(
        "DOCX", path, archive, media_names, locators=locators
    )


def _images_from_archive(
    format_name: str,
    path: str,
    archive: zipfile.ZipFile,
    media_names: list[str],
    *,
    locators: list[str] | None = None,
) -> list[DocumentImage]:
    """Load bounded image entries for a relationship-resolved ZIP document."""
    if len(media_names) > MAX_DOCUMENT_IMAGES:
        raise DocumentReadError(
            f"{format_name} declares {len(media_names)} media entries; "
            f"limit is {MAX_DOCUMENT_IMAGES}"
        )
    images: list[DocumentImage] = []
    if locators is not None and len(locators) != len(media_names):
        raise DocumentReadError(
            f"{format_name} image locator count does not match media"
        )
    for index, media_path in enumerate(media_names, start=1):
        suffix = PurePosixPath(media_path).suffix.lower()
        mime = _IMAGE_SUFFIX_MIME.get(suffix)
        if mime is None:
            raise DocumentReadError(
                f"{format_name} media {media_path} has unsupported image type "
                f"{suffix or '<none>'}"
            )
        try:
            data = archive.read(media_path)
        except KeyError as exc:
            raise DocumentReadError(
                f"{format_name} media {media_path} is declared but unreadable"
            ) from exc
        if not data:
            raise DocumentReadError(f"{format_name} media {media_path} is empty")
        if len(data) > MAX_DOCUMENT_IMAGE_BYTES:
            raise DocumentReadError(
                f"{format_name} media {media_path} exceeds the bounded "
                f"{MAX_DOCUMENT_IMAGE_BYTES} byte image size"
            )
        images.append(
            DocumentImage(
                path=path,
                media_path=media_path,
                mime_type=mime,
                data=data,
                locator=(locators[index - 1] if locators else f"figure-{index}"),
            )
        )
    return images


def _paragraph_text(paragraph: ET.Element) -> str:
    """Keep visible Word text, tabs, breaks, and Office Math runs."""
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag in {f"{W}t", f"{W}instrText", f"{M}t"}:
            parts.append(element.text or "")
        elif element.tag == f"{W}tab":
            parts.append("\t")
        elif element.tag in {f"{W}br", f"{W}cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _table_markdown(table: ET.Element, table_number: int) -> str:
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


def _xml_local_name(tag: str) -> str:
    """Return an XML element's local name without trusting its prefix."""
    return tag.rsplit("}", 1)[-1]


def _safe_hwpx_section_path(href: str) -> str:
    """Resolve one manifest section href inside the HWPX Contents directory."""
    target = PurePosixPath(href)
    if (
        not href
        or target.is_absolute()
        or ".." in target.parts
        or "\\" in href
        or "?" in href
        or "#" in href
    ):
        raise DocumentReadError("HWPX section relationship targets outside Contents")
    section_path = href if href.startswith("Contents/") else f"Contents/{href}"
    return section_path


def _safe_hwpx_media_path(
    relationship_id: str,
    href: str,
    media_type: str,
    is_embedded: str,
) -> str:
    """Validate one section image relationship against the HWPX manifest."""
    if is_embedded == "0":
        raise DocumentReadError(
            f"HWPX image {relationship_id} uses an external relationship"
        )
    target = PurePosixPath(href)
    if (
        not href
        or target.is_absolute()
        or ".." in target.parts
        or "\\" in href
        or "?" in href
        or "#" in href
        or not href.startswith("BinData/")
    ):
        raise DocumentReadError(
            f"HWPX image relationship {relationship_id} targets outside BinData"
        )
    suffix = target.suffix.lower()
    if not media_type.casefold().startswith("image/") or suffix not in _IMAGE_SUFFIX_MIME:
        raise DocumentReadError(
            f"HWPX image relationship {relationship_id} has unsupported image media"
        )
    return href


def _hwpx_picture_references(
    section_root: ET.Element,
    *,
    section_number: int,
    manifest_items: dict[str, tuple[str, str, str]],
) -> tuple[list[str], list[str]]:
    """Resolve picture references in semantic XML order with stable locators."""
    media_names: list[str] = []
    locators: list[str] = []

    def walk(element: ET.Element, path: str) -> None:
        sibling_counts: dict[str, int] = {}
        for child in element:
            local_name = _xml_local_name(child.tag)
            sibling_counts[local_name] = sibling_counts.get(local_name, 0) + 1
            child_path = f"{path}/{local_name}-{sibling_counts[local_name]}"
            if local_name == "pic":
                image_elements = [
                    descendant
                    for descendant in child.iter()
                    if _xml_local_name(descendant.tag) == "img"
                    and "binaryItemIDRef" in descendant.attrib
                ]
                if len(image_elements) != 1:
                    raise DocumentReadError(
                        "HWPX picture has missing or ambiguous image relationship"
                    )
                relationship_id = image_elements[0].attrib["binaryItemIDRef"].strip()
                item = manifest_items.get(relationship_id)
                if not relationship_id or item is None:
                    raise DocumentReadError(
                        f"HWPX picture has unresolved relationship "
                        f"{relationship_id or '<missing>'}"
                    )
                href, media_type, is_embedded = item
                media_path = _safe_hwpx_media_path(
                    relationship_id, href, media_type, is_embedded
                )
                media_names.append(media_path)
                locators.append(
                    f"section-{section_number}:{child_path}:"
                    f"{relationship_id}->{media_path}"
                )
            walk(child, child_path)

    walk(section_root, f"section-{section_number}")
    return media_names, locators


def _hwpx_media_references(raw: bytes) -> tuple[list[str], list[str]]:
    """Resolve manifest-bound HWPX images in spine and section source order."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCUMENT_ZIP_ENTRIES:
                raise DocumentReadError("HWPX archive has too many entries")
            if (
                sum(info.file_size for info in infos)
                > MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES
            ):
                raise DocumentReadError(
                    "HWPX archive exceeds the bounded unpacked size"
                )
            entry_names = [info.filename for info in infos if not info.is_dir()]
            if len(entry_names) != len(set(entry_names)):
                raise DocumentReadError("HWPX archive has duplicate entry names")
            image_entries = {
                name
                for name in entry_names
                if PurePosixPath(name).suffix.lower() in _IMAGE_SUFFIX_MIME
            }
            if not image_entries:
                return [], []
            try:
                content_xml = archive.read("Contents/content.hpf")
            except KeyError as exc:
                raise DocumentReadError(
                    "HWPX image archive has no Contents/content.hpf"
                ) from exc
            try:
                content_root = ET.fromstring(content_xml)
            except (ET.ParseError, DefusedXmlException) as exc:
                raise DocumentReadError("HWPX content.hpf is malformed") from exc

            manifest_items: dict[str, tuple[str, str, str]] = {}
            manifest_order: list[str] = []
            for element in content_root.iter():
                if _xml_local_name(element.tag) != "item":
                    continue
                item_id = element.attrib.get("id", "").strip()
                href = element.attrib.get("href", "").strip()
                if not item_id or not href:
                    continue
                if item_id in manifest_items:
                    raise DocumentReadError(
                        f"HWPX has duplicate manifest ID {item_id}"
                    )
                manifest_items[item_id] = (
                    href,
                    element.attrib.get("media-type", "").strip(),
                    element.attrib.get("isEmbeded", "1").strip(),
                )
                manifest_order.append(item_id)

            spine_ids = [
                element.attrib.get("idref", "").strip()
                for element in content_root.iter()
                if _xml_local_name(element.tag) == "itemref"
                and element.attrib.get("idref", "").strip()
            ]
            section_ids = [
                item_id
                for item_id in (spine_ids or manifest_order)
                if item_id in manifest_items
                and manifest_items[item_id][1] == "application/xml"
                and "section" in manifest_items[item_id][0].casefold()
            ]
            if not section_ids:
                raise DocumentReadError(
                    "HWPX image archive has no manifest-bound section relationship"
                )

            media_names: list[str] = []
            locators: list[str] = []
            for section_number, section_id in enumerate(section_ids, start=1):
                section_path = _safe_hwpx_section_path(
                    manifest_items[section_id][0]
                )
                try:
                    section_xml = archive.read(section_path)
                except KeyError as exc:
                    raise DocumentReadError(
                        f"HWPX section relationship {section_id} is unreadable"
                    ) from exc
                try:
                    section_root = ET.fromstring(section_xml)
                except (ET.ParseError, DefusedXmlException) as exc:
                    raise DocumentReadError(
                        f"HWPX section relationship {section_id} is malformed"
                    ) from exc
                section_media, section_locators = _hwpx_picture_references(
                    section_root,
                    section_number=section_number,
                    manifest_items=manifest_items,
                )
                media_names.extend(section_media)
                locators.extend(section_locators)

            if not media_names and image_entries:
                raise DocumentReadError(
                    "HWPX archive media is not referenced by any section picture"
                )
            return media_names, locators
    except DocumentReadError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError):
        # Classic .hwp is not a ZIP; absence of ZIP media is not evidence of
        # figures, so the text reader path remains authoritative.
        return [], []


def _hwpx_media_names(raw: bytes) -> list[str]:
    """Return manifest-bound HWPX image paths in section source order."""
    return _hwpx_media_references(raw)[0]


def _extract_hwp_bundle(path: str, raw: bytes) -> DocumentExtraction:
    """Extract HWP/HWPX text and fail closed on unattached archive media."""
    suffix = PurePosixPath(path).suffix.lower()
    media_names, locators = (
        _hwpx_media_references(raw) if suffix == ".hwpx" else ([], [])
    )
    text = _extract_hwp_with_reviewed_reader(path, raw)
    images: list[DocumentImage] = []
    if media_names:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                images = _images_from_archive(
                    "HWPX", path, archive, media_names, locators=locators
                )
        except DocumentReadError:
            raise
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise DocumentReadError(
                f"{path}: HWPX declares image media but the archive is unreadable"
            ) from exc
    return DocumentExtraction(
        path=path,
        text=_bounded_text(f"[document text] path={path}\n{text}"),
        images=images,
        media_declared=len(media_names),
    )


def _extract_hwp_with_reviewed_reader(path: str, raw: bytes) -> str:
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
    if not text:
        raise DocumentReadError("reviewed hwp-mcp/rhwp reader returned empty text")
    return text


def _bounded_text(text: str) -> str:
    """Bound reader output before it enters the review prompt."""
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_DOCUMENT_TEXT_BYTES:
        return text
    clipped = encoded[:MAX_DOCUMENT_TEXT_BYTES].decode("utf-8", errors="ignore")
    omitted = len(encoded) - len(clipped.encode("utf-8"))
    return f"{clipped}\n[document text truncated; {omitted} bytes omitted]"


def _main() -> int:
    """Provide a local, byte-safe smoke-test CLI for one document."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument(
        "--allow-figures",
        action="store_true",
        help="Print text even when figures are present (does not emit image bytes).",
    )
    args = parser.parse_args()
    try:
        with open(args.path, "rb") as handle:
            raw = handle.read()
        if args.allow_figures:
            bundle = extract_review_document_bundle(args.path, raw)
            print(bundle.text)
            print(f"[figures attached: {len(bundle.images)}]", file=os.sys.stderr)
        else:
            print(extract_review_document(args.path, raw))
    except (OSError, DocumentReadError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
