"""Unit tests for Noema document multimodal extraction edge cases."""

from __future__ import annotations

import io
import os
import subprocess
import warnings
import zipfile
from pathlib import Path

import pytest

from scripts.ci import noema_review_document as document


def _minimal_docx_xml(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>{body}</w:body>
</w:document>"""


def _docx_blip(relationship_id: str) -> str:
    """Return one minimal document-order image reference."""
    return f'<w:p><w:r><w:drawing><a:blip r:embed="{relationship_id}"/></w:drawing></w:r></w:p>'


def _write_docx(
    *,
    body: str = "<w:p><w:r><w:t>hello</w:t></w:r></w:p>",
    media: dict[str, bytes] | None = None,
    include_document_xml: bool = True,
    extra_entries: int = 0,
    relationships: dict[str, str] | None = None,
    include_relationships: bool = True,
    relationships_xml: str | None = None,
) -> bytes:
    media = media or {}
    if relationships is None:
        relationships = {
            f"rId{index}": name.removeprefix("word/")
            for index, name in enumerate(media, start=1)
        }
        if media and "r:embed=" not in body:
            body += "".join(_docx_blip(relationship_id) for relationship_id in relationships)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if include_document_xml:
            archive.writestr("word/document.xml", _minimal_docx_xml(body))
        if relationships_xml is None and include_relationships and relationships:
            rows = "".join(
                '<Relationship Id="{}" Type="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships/image" Target="{}"/>'.format(
                    relationship_id, target
                )
                for relationship_id, target in relationships.items()
            )
            relationships_xml = (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f"{rows}</Relationships>"
            )
        if relationships_xml is not None:
            archive.writestr("word/_rels/document.xml.rels", relationships_xml)
        for name, data in media.items():
            archive.writestr(name, data)
        for index in range(extra_entries):
            archive.writestr(f"padding/{index}.txt", b"x")
    return output.getvalue()


def _write_hwpx(
    *,
    sections: dict[str, tuple[str, str]],
    spine: list[str],
    media: dict[str, tuple[str, bytes]],
    extra_media: dict[str, bytes] | None = None,
    manifest_rows: str | None = None,
) -> bytes:
    """Build a synthetic HWPX package with manifest-bound image references."""
    if manifest_rows is None:
        manifest_rows = "".join(
            '<opf:item id="{}" href="{}" media-type="image/png" isEmbeded="1"/>'.format(
                item_id, href
            )
            for item_id, (href, _data) in media.items()
        )
        manifest_rows += "".join(
            '<opf:item id="{}" href="{}" media-type="application/xml"/>'.format(
                section_id, section_path
            )
            for section_id, (section_path, _xml) in sections.items()
        )
    content_hpf = (
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/">'
        f"<opf:manifest>{manifest_rows}</opf:manifest>"
        "<opf:spine>"
        + "".join(f'<opf:itemref idref="{section_id}"/>' for section_id in spine)
        + "</opf:spine></opf:package>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Contents/content.hpf", content_hpf)
        for section_path, xml in sections.values():
            archive.writestr(section_path, xml)
        for href, data in media.values():
            archive.writestr(href, data)
        for href, data in (extra_media or {}).items():
            archive.writestr(href, data)
    return output.getvalue()


def _hwpx_section(*binary_refs: str) -> str:
    """Return section XML whose nested pictures preserve the supplied order."""
    pictures = "".join(
        '<hp:p><hp:run><hp:pic><hc:img binaryItemIDRef="{}"/></hp:pic>'
        "</hp:run></hp:p>".format(binary_ref)
        for binary_ref in binary_refs
    )
    return (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">'
        f"{pictures}</hs:sec>"
    )


def _hwpx_table_section(first_ref: str, table_ref: str) -> str:
    """Return a section with figures in a text run and a nested table cell."""
    return (
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
        'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core">'
        f'<hp:p><hp:run><hp:pic><hc:img binaryItemIDRef="{first_ref}"/>'
        "</hp:pic></hp:run></hp:p>"
        "<hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:pic>"
        f'<hc:img binaryItemIDRef="{table_ref}"/>'
        "</hp:pic></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl>"
        "</hs:sec>"
    )


def _write_zip(entries: list[tuple[str, str | bytes]]) -> bytes:
    """Build a synthetic ZIP while preserving entry order and duplicates."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message="Duplicate name:.*", category=UserWarning
                )
                archive.writestr(name, data)
    return output.getvalue()
def test_document_extraction_rejects_missing_attached_figures():
    """Declared media without attached images must fail closed."""
    extraction = document.DocumentExtraction(
        path="docs/x.docx", text="t", images=[], media_declared=1
    )
    with pytest.raises(document.DocumentReadError, match="no image parts were attached"):
        extraction.ensure_figures_attached()


def test_document_extraction_rejects_partial_figure_coverage():
    """Partial figure attachment must fail closed."""
    image = document.DocumentImage(
        path="docs/x.docx",
        media_path="word/media/a.png",
        mime_type="image/png",
        data=b"png",
        locator="figure-1",
    )
    extraction = document.DocumentExtraction(
        path="docs/x.docx", text="t", images=[image], media_declared=2
    )
    with pytest.raises(document.DocumentReadError, match="partial"):
        extraction.ensure_figures_attached()


def test_document_image_multimodal_parts_shape():
    """Each figure emits a locator text part and a data-URL image part."""
    image = document.DocumentImage(
        path="docs/x.docx",
        media_path="word/media/a.png",
        mime_type="image/png",
        data=b"png",
        locator="figure-1",
    )
    parts = image.to_multimodal_parts()
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_extract_review_document_rejects_oversized_input():
    """Oversized archives are rejected before parsing."""
    raw = b"x" * (document.MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(document.DocumentReadError, match="8 MiB"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_extract_review_document_rejects_unsupported_suffix():
    """Unknown suffixes fail closed."""
    with pytest.raises(document.DocumentReadError, match="unsupported review document format"):
        document.extract_review_document_bundle("docs/x.pdf", b"data")


def test_docx_rejects_too_many_zip_entries():
    """DOCX entry-count bounds are enforced."""
    raw = _write_docx(extra_entries=document.MAX_DOCUMENT_ZIP_ENTRIES)
    with pytest.raises(document.DocumentReadError, match="too many entries"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_missing_document_xml():
    """DOCX without word/document.xml fails closed."""
    raw = _write_docx(include_document_xml=False)
    with pytest.raises(document.DocumentReadError, match="no word/document.xml"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_missing_body():
    """DOCX without a body element fails closed."""
    xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:p><w:r><w:t>orphan</w:t></w:r></w:p></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
    with pytest.raises(document.DocumentReadError, match="no document body"):
        document.extract_review_document_bundle("docs/x.docx", output.getvalue())


def test_docx_image_only_body_is_allowed():
    """Figure-only DOCX archives still produce bounded text."""
    png = b"\x89PNG\r\n\x1a\n"
    raw = _write_docx(body="", media={"word/media/a.png": png})
    bundle = document.extract_review_document_bundle("docs/x.docx", raw)
    assert "figures attached separately" in bundle.text
    assert len(bundle.images) == 1


def test_docx_uses_relationship_order_and_ignores_orphan_media():
    """Only body-referenced figures are attached, in document source order."""
    png = b"\x89PNG\r\n\x1a\n"
    raw = _write_docx(
        body=_docx_blip("rIdSecond") + _docx_blip("rIdFirst"),
        media={
            "word/media/a.png": png,
            "word/media/z.png": png,
            "word/media/orphan.png": png,
        },
        relationships={
            "rIdFirst": "media/a.png",
            "rIdSecond": "media/z.png",
        },
    )

    bundle = document.extract_review_document_bundle("docs/x.docx", raw)

    assert [image.media_path for image in bundle.images] == [
        "word/media/z.png",
        "word/media/a.png",
    ]
    assert [image.locator for image in bundle.images] == [
        "document-body-blip-1:rIdSecond->word/media/z.png",
        "document-body-blip-2:rIdFirst->word/media/a.png",
    ]
    assert bundle.media_declared == 2


def test_docx_rejects_unresolved_body_image_relationship():
    """A body figure with no internal relationship must fail closed."""
    raw = _write_docx(
        body=_docx_blip("rIdMissing"),
        media={"word/media/a.png": b"png"},
        include_relationships=False,
    )

    with pytest.raises(document.DocumentReadError, match="unresolved relationship"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_image_relationship_outside_media_directory():
    """A relationship cannot escape the bounded DOCX media directory."""
    raw = _write_docx(
        body=_docx_blip("rIdEscape"),
        media={"outside.png": b"png"},
        relationships={"rIdEscape": "../outside.png"},
    )

    with pytest.raises(document.DocumentReadError, match="outside word/media"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_relationship_traversal_that_reenters_media_directory():
    """Normalizing back into word/media must not erase a traversal attempt."""
    raw = _write_docx(
        body=_docx_blip("rIdEscape"),
        media={"word/media/a.png": b"png"},
        relationships={"rIdEscape": "media/../../word/media/a.png"},
    )

    with pytest.raises(document.DocumentReadError, match="outside word/media"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_duplicate_relationship_ids():
    """Duplicate relationship IDs are ambiguous and must fail closed."""
    relationships_xml = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/image" Target="media/a.png"/>'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/image" Target="media/b.png"/>'
        "</Relationships>"
    )
    raw = _write_docx(
        body=_docx_blip("rId1"),
        media={"word/media/a.png": b"a", "word/media/b.png": b"b"},
        relationships_xml=relationships_xml,
    )

    with pytest.raises(document.DocumentReadError, match="duplicate relationship ID"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_external_target_mode_is_case_insensitive():
    """Lowercase external image relationships must not authorize archive media."""
    relationships_xml = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/image" Target="media/a.png" '
        'TargetMode="external"/>'
        "</Relationships>"
    )
    raw = _write_docx(
        body=_docx_blip("rId1"),
        media={"word/media/a.png": b"a"},
        relationships_xml=relationships_xml,
    )

    with pytest.raises(document.DocumentReadError, match="unresolved relationship"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_malformed_relationship_xml():
    """Malformed relationship XML fails closed before image resolution."""
    raw = _write_docx(
        body=_docx_blip("rId1"),
        relationships_xml="<Relationships",
    )

    with pytest.raises(document.DocumentReadError, match="relationships are malformed"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_ignores_relationship_without_id_then_fails_reference():
    """A relationship without an ID cannot satisfy a body reference."""
    relationships_xml = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/image" Target="media/a.png"/>'
        "</Relationships>"
    )
    raw = _write_docx(
        body=_docx_blip("rId1"),
        media={"word/media/a.png": b"a"},
        relationships_xml=relationships_xml,
    )

    with pytest.raises(document.DocumentReadError, match="unresolved relationship"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_sibling_media_directory_prefix():
    """A word/media2 target must not satisfy the word/media boundary."""
    raw = _write_docx(
        body=_docx_blip("rId1"),
        media={"word/media2/a.png": b"a"},
        relationships={"rId1": "media2/a.png"},
    )

    with pytest.raises(document.DocumentReadError, match="outside word/media"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_locator_media_cardinality_mismatch():
    """Internal locator and media cardinality must stay one-to-one."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/media/a.png", b"a")
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        with pytest.raises(document.DocumentReadError, match="locator count"):
            document._docx_images_from_archive(
                "docs/x.docx",
                archive,
                ["word/media/a.png"],
                locators=[],
            )


def test_docx_rejects_too_many_media_entries():
    """Media count limits are enforced."""
    media = {f"word/media/{index}.png": b"x" for index in range(document.MAX_DOCUMENT_IMAGES + 1)}
    raw = _write_docx(media=media)
    with pytest.raises(document.DocumentReadError, match="limit is"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_empty_media_bytes():
    """Empty media entries fail closed."""
    raw = _write_docx(media={"word/media/a.png": b""})
    with pytest.raises(document.DocumentReadError, match="is empty"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_oversized_media_bytes():
    """Oversized images fail closed."""
    raw = _write_docx(
        media={"word/media/a.png": b"x" * (document.MAX_DOCUMENT_IMAGE_BYTES + 1)}
    )
    with pytest.raises(document.DocumentReadError, match="bounded"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_paragraph_text_preserves_tabs_and_breaks():
    """Tabs and line breaks inside paragraphs are preserved."""
    xml = _minimal_docx_xml(
        "<w:p><w:r><w:t>a</w:t></w:r><w:tab/><w:br/><w:r><w:t>b</w:t></w:r></w:p>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", xml)
    bundle = document.extract_review_document_bundle("docs/x.docx", output.getvalue())
    assert "a\t\nb" in bundle.text


def test_docx_skips_empty_paragraphs_and_tables():
    """Empty paragraphs and tables are omitted from the text envelope."""
    body = "<w:p></w:p><w:tbl><w:tr></w:tr></w:tbl><w:p><w:r><w:t>kept</w:t></w:r></w:p>"
    raw = _write_docx(body=body)
    bundle = document.extract_review_document_bundle("docs/x.docx", raw)
    assert "kept" in bundle.text
    assert "### Table" not in bundle.text


def test_docx_ignores_non_paragraph_body_children():
    """Section properties and other body children are skipped safely."""
    body = (
        "<w:sectPr/>"
        "<w:p><w:r><w:t>kept</w:t></w:r></w:p>"
    )
    raw = _write_docx(body=body)
    bundle = document.extract_review_document_bundle("docs/x.docx", raw)
    assert "kept" in bundle.text


def test_docx_table_only_empty_rows_fail_without_figures():
    """A table-only DOCX with no renderable rows still fails without figures."""
    raw = _write_docx(body="<w:tbl><w:tr></w:tr></w:tbl>")
    with pytest.raises(document.DocumentReadError, match="no readable text"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_table_markdown_escapes_pipes_and_skips_empty_tables():
    """Tables render as markdown and empty tables are omitted."""
    body = (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>a|b</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "<w:tbl></w:tbl>"
    )
    raw = _write_docx(body=body)
    bundle = document.extract_review_document_bundle("docs/x.docx", raw)
    assert "a\\|b" in bundle.text
    assert "### Table 1" in bundle.text


def test_hwpx_media_discovery_and_attachment(monkeypatch):
    """Manifest-bound HWPX media is attached alongside reviewed reader text."""
    png = b"\x89PNG\r\n\x1a\n"
    raw = _write_hwpx(
        sections={
            "section0": ("Contents/section0.xml", _hwpx_section("image1"))
        },
        spine=["section0"],
        media={"image1": ("BinData/image1.png", png)},
    )
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = subprocess.CompletedProcess(
        ["node"], 0, stdout=b"HWPX-TEXT\n", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)
    bundle = document.extract_review_document_bundle("docs/x.hwpx", raw)
    assert "HWPX-TEXT" in bundle.text
    assert len(bundle.images) == 1


def test_hwpx_uses_manifest_and_section_order_with_reused_image(monkeypatch):
    """HWPX figures follow spine/section order, not ZIP or filename order."""
    png_a = b"\x89PNG\r\n\x1a\nA"
    png_b = b"\x89PNG\r\n\x1a\nB"
    raw = _write_hwpx(
        sections={
            "section0": ("Contents/section0.xml", _hwpx_section("imageA")),
            "section1": (
                "Contents/section1.xml",
                _hwpx_section("imageB", "imageA"),
            ),
        },
        spine=["section1", "section0"],
        media={
            "imageA": ("BinData/a.png", png_a),
            "imageB": ("BinData/b.png", png_b),
        },
        extra_media={"BinData/orphan.png": b"orphan"},
    )
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    monkeypatch.setattr(
        document.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["node"], 0, stdout=b"HWPX-TEXT\n", stderr=b""
        ),
    )

    bundle = document.extract_review_document_bundle("docs/x.hwpx", raw)

    assert [image.media_path for image in bundle.images] == [
        "BinData/b.png",
        "BinData/a.png",
        "BinData/a.png",
    ]
    assert [image.data for image in bundle.images] == [png_b, png_a, png_a]
    assert bundle.media_declared == 3
    assert "section-1" in bundle.images[0].locator
    assert "imageB->BinData/b.png" in bundle.images[0].locator
    assert "section-2" in bundle.images[2].locator
    assert "imageA->BinData/a.png" in bundle.images[2].locator
    assert all(image.data != b"orphan" for image in bundle.images)


def test_hwpx_locator_preserves_text_run_and_table_cell_positions(monkeypatch):
    """Stable locators distinguish paragraph and table-cell picture positions."""
    raw = _write_hwpx(
        sections={
            "section0": (
                "Contents/section0.xml",
                _hwpx_table_section("imageB", "imageA"),
            )
        },
        spine=["section0"],
        media={
            "imageA": ("BinData/a.png", b"a"),
            "imageB": ("BinData/b.png", b"b"),
        },
    )
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    monkeypatch.setattr(
        document.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["node"], 0, stdout=b"HWPX-TEXT\n", stderr=b""
        ),
    )

    bundle = document.extract_review_document_bundle("docs/x.hwpx", raw)

    assert [image.media_path for image in bundle.images] == [
        "BinData/b.png",
        "BinData/a.png",
    ]
    assert "/p-1/run-1/pic-1:" in bundle.images[0].locator
    assert "/tbl-1/tr-1/tc-1/subList-1/p-1/run-1/pic-1:" in bundle.images[1].locator


def test_hwpx_relationship_helpers_reject_invalid_shapes():
    """Direct relationship helpers reject unsafe paths and missing picture refs."""
    with pytest.raises(document.DocumentReadError, match="outside Contents"):
        document._safe_hwpx_section_path("../section0.xml")
    with pytest.raises(document.DocumentReadError, match="unsupported image media"):
        document._safe_hwpx_media_path(
            "image1", "BinData/image1.bin", "application/octet-stream", "1"
        )
    picture_without_image = document.ET.fromstring("<root><pic/></root>")
    with pytest.raises(document.DocumentReadError, match="missing or ambiguous"):
        document._hwpx_picture_references(
            picture_without_image,
            section_number=1,
            manifest_items={},
        )


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            [("BinData/a.png", b"a"), ("BinData/a.png", b"b")],
            "duplicate entry names",
        ),
        ([("BinData/a.png", b"a")], "no Contents/content.hpf"),
        (
            [("BinData/a.png", b"a"), ("Contents/content.hpf", "<broken")],
            "content.hpf is malformed",
        ),
        (
            [
                ("BinData/a.png", b"a"),
                (
                    "Contents/content.hpf",
                    '<package><item id="" href=""/><manifest/></package>',
                ),
            ],
            "no manifest-bound section relationship",
        ),
        (
            [
                ("BinData/a.png", b"a"),
                (
                    "Contents/content.hpf",
                    '<package><item id="section0" href="Contents/section-missing.xml" '
                    'media-type="application/xml"/><itemref idref="section0"/></package>',
                ),
            ],
            "section relationship section0 is unreadable",
        ),
        (
            [
                ("BinData/a.png", b"a"),
                (
                    "Contents/content.hpf",
                    '<package><item id="section0" href="Contents/section0.xml" '
                    'media-type="application/xml"/><itemref idref="section0"/></package>',
                ),
                ("Contents/section0.xml", "<broken"),
            ],
            "section relationship section0 is malformed",
        ),
        (
            [
                ("BinData/a.png", b"a"),
                (
                    "Contents/content.hpf",
                    '<package><item id="section0" href="Contents/section0.xml" '
                    'media-type="application/xml"/><itemref idref="section0"/></package>',
                ),
                ("Contents/section0.xml", "<section/>"),
            ],
            "not referenced by any section picture",
        ),
    ],
)
def test_hwpx_malformed_package_boundaries_fail_closed(entries, message):
    """Malformed package and section boundaries never fall back to filename order."""
    with pytest.raises(document.DocumentReadError, match=message):
        document._hwpx_media_references(_write_zip(entries))


def test_hwpx_without_image_entries_has_no_multimodal_references():
    """A text-only archive does not invent image relationships."""
    raw = _write_zip([("Contents/section0.xml", "<section/>")])
    assert document._hwpx_media_references(raw) == ([], [])


@pytest.mark.parametrize(
    ("manifest_rows", "section", "message"),
    [
        (
            '<opf:item id="image1" href="BinData/a.png" media-type="image/png"/>'
            '<opf:item id="image1" href="BinData/b.png" media-type="image/png"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>',
            _hwpx_section("image1"),
            "duplicate manifest ID",
        ),
        (
            '<opf:item id="image1" href="../BinData/a.png" media-type="image/png"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>',
            _hwpx_section("image1"),
            "outside BinData",
        ),
        (
            '<opf:item id="image1" href="BinData/a.png" media-type="image/png" isEmbeded="0"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>',
            _hwpx_section("image1"),
            "external relationship",
        ),
        (
            '<opf:item id="image1" href="BinData/a.png" media-type="image/png"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>',
            _hwpx_section("missing"),
            "unresolved relationship",
        ),
    ],
)
def test_hwpx_rejects_ambiguous_or_unsafe_image_relationships(
    monkeypatch, manifest_rows, section, message
):
    """HWPX image admission fails closed on ambiguous or unsafe mappings."""
    raw = _write_hwpx(
        sections={"section0": ("Contents/section0.xml", section)},
        spine=["section0"],
        media={"image1": ("BinData/a.png", b"png")},
        manifest_rows=manifest_rows,
    )
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    monkeypatch.setattr(
        document.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["node"], 0, stdout=b"HWPX-TEXT\n", stderr=b""
        ),
    )

    with pytest.raises(document.DocumentReadError, match=message):
        document.extract_review_document_bundle("docs/x.hwpx", raw)


def test_hwpx_non_zip_input_has_no_media_names():
    """Classic HWP bytes are not treated as ZIP media containers."""
    assert document._hwpx_media_names(b"not-a-zip") == []


def test_hwpx_unreadable_archive_with_media_fails_closed(monkeypatch):
    """Broken HWPX media archives fail closed."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = subprocess.CompletedProcess(
        ["node"], 0, stdout=b"HWPX-TEXT\n", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)

    def broken_zip(*args, **kwargs):
        raise zipfile.BadZipFile("broken")

    monkeypatch.setattr(document.zipfile, "ZipFile", broken_zip)
    monkeypatch.setattr(
        document,
        "_hwpx_media_references",
        lambda raw: (["BinData/image1.png"], ["section-1/p-1:image1"]),
    )
    with pytest.raises(document.DocumentReadError, match="unreadable"):
        document.extract_review_document_bundle("docs/x.hwpx", b"zip")


def test_hwp_reader_missing_configuration(monkeypatch):
    """Missing reader configuration fails closed."""
    monkeypatch.delenv(document.HWP_READER_ENV, raising=False)
    with pytest.raises(document.DocumentReadError, match="not configured"):
        document.extract_review_document_bundle("docs/x.hwp", b"binary")


def test_hwp_reader_additional_failure_paths(monkeypatch):
    """Additional reviewed-reader subprocess failures are bounded."""
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")

    def start_failure(*args, **kwargs):
        raise OSError("node missing")

    monkeypatch.setattr(document.subprocess, "run", start_failure)
    with pytest.raises(document.DocumentReadError, match="could not start"):
        document.extract_review_document("docs/x.hwp", b"binary")

    monkeypatch.setattr(
        document.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["node"], 0, stdout=b"x" * (document.MAX_DOCUMENT_TEXT_BYTES + 1), stderr=b""
        ),
    )
    with pytest.raises(document.DocumentReadError, match="exceeded the bounded output"):
        document.extract_review_document("docs/x.hwp", b"binary")

    monkeypatch.setattr(
        document.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["node"], 0, stdout=b"\xff\xfe", stderr=b""
        ),
    )
    with pytest.raises(document.DocumentReadError, match="non-UTF-8"):
        document.extract_review_document("docs/x.hwp", b"binary")

    monkeypatch.setattr(
        document.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            ["node"], 0, stdout=b"   \n", stderr=b""
        ),
    )
    with pytest.raises(document.DocumentReadError, match="empty text"):
        document.extract_review_document("docs/x.hwp", b"binary")


def test_bounded_text_truncates_large_output():
    """Reader output is clipped to the bounded text budget."""
    clipped = document._bounded_text("x" * (document.MAX_DOCUMENT_TEXT_BYTES + 50))
    assert "truncated" in clipped


def test_docx_rejects_unpacked_size_limit(monkeypatch):
    """DOCX unpacked-size bounds are enforced from ZipInfo metadata."""
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 16)
    raw = _write_docx(body="<w:p><w:r><w:t>this body exceeds the test limit</w:t></w:r></w:p>")
    with pytest.raises(document.DocumentReadError, match="bounded unpacked size"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_rejects_textless_body_without_figures():
    """Empty DOCX bodies without figures fail closed."""
    raw = _write_docx(body="")
    with pytest.raises(document.DocumentReadError, match="no readable text"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_docx_media_read_keyerror_is_fail_closed(monkeypatch):
    """Unreadable declared media entries fail closed."""
    raw = _write_docx(media={"word/media/a.png": b"png"})

    class BrokenZip(zipfile.ZipFile):
        def read(self, name, pwd=None):
            if name == "word/media/a.png":
                raise KeyError(name)
            return super().read(name, pwd)

    monkeypatch.setattr(document.zipfile, "ZipFile", BrokenZip)
    with pytest.raises(document.DocumentReadError, match="declared but unreadable"):
        document.extract_review_document_bundle("docs/x.docx", raw)


def test_hwpx_rejects_too_many_zip_entries():
    """HWPX entry-count bounds are enforced."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for index in range(document.MAX_DOCUMENT_ZIP_ENTRIES + 1):
            archive.writestr(f"entry/{index}.txt", b"x")
    with pytest.raises(document.DocumentReadError, match="too many entries"):
        document._hwpx_media_names(output.getvalue())


def test_hwpx_rejects_unpacked_size_limit(monkeypatch):
    """HWPX unpacked-size bounds are enforced."""
    monkeypatch.setattr(document, "MAX_DOCUMENT_ZIP_UNCOMPRESSED_BYTES", 16)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Contents/section0.xml", b"<section>too-large-for-limit</section>")
    with pytest.raises(document.DocumentReadError, match="bounded unpacked size"):
        document._hwpx_media_names(output.getvalue())


def test_hwpx_skips_directory_entries():
    """Directory entries are ignored during HWPX media discovery."""
    raw = _write_hwpx(
        sections={
            "section0": ("Contents/section0.xml", _hwpx_section("image1"))
        },
        spine=["section0"],
        media={"image1": ("BinData/image1.png", b"png")},
        extra_media={"BinData/": b""},
    )
    assert document._hwpx_media_names(raw) == ["BinData/image1.png"]


def test_hwpx_empty_media_bytes_fail_closed(monkeypatch):
    """Empty HWPX media entries fail closed during bundle extraction."""
    raw = _write_hwpx(
        sections={
            "section0": ("Contents/section0.xml", _hwpx_section("image1"))
        },
        spine=["section0"],
        media={"image1": ("BinData/image1.png", b"")},
    )
    monkeypatch.setenv(document.HWP_READER_ENV, "/trusted/hwp-mcp-source")
    completed = subprocess.CompletedProcess(
        ["node"], 0, stdout=b"HWPX-TEXT\n", stderr=b""
    )
    monkeypatch.setattr(document.subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(document.DocumentReadError, match="is empty"):
        document.extract_review_document_bundle("docs/x.hwpx", raw)


def test_module_main_entrypoint(tmp_path: Path, monkeypatch):
    """Running the module as __main__ exits through the CLI wrapper."""
    import runpy
    import sys

    docx = tmp_path / "sample.docx"
    docx.write_bytes(_write_docx())
    monkeypatch.setattr(
        document,
        "extract_review_document",
        lambda path, raw: "MAIN-TEXT",
    )
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(docx)])
    with pytest.warns(RuntimeWarning, match="found in sys.modules"):
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("scripts.ci.noema_review_document", run_name="__main__")
    assert exc.value.code == 0


def test_main_cli_smoke(tmp_path: Path, monkeypatch, capsys):
    """The module CLI prints extracted text for local smoke tests."""
    import sys

    docx = tmp_path / "sample.docx"
    docx.write_bytes(_write_docx())
    monkeypatch.setattr(
        document,
        "extract_review_document",
        lambda path, raw: "CLI-TEXT",
    )
    monkeypatch.setattr(
        document,
        "extract_review_document_bundle",
        lambda path, raw: document.DocumentExtraction(path=path, text="CLI-BUNDLE", images=[]),
    )
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(docx)])
    assert document._main() == 0
    assert "CLI-TEXT" in capsys.readouterr().out

    monkeypatch.setattr(
        sys,
        "argv",
        ["noema_review_document.py", str(docx), "--allow-figures"],
    )
    assert document._main() == 0

    missing = tmp_path / "missing.docx"
    monkeypatch.setattr(sys, "argv", ["noema_review_document.py", str(missing)])
    assert document._main() == 1
