"""Exercise DOCX structural admission through the production policy boundary offline."""
import io
import os
import zipfile

import pytest
from tests.test_pingora_edge_policy import policy
from tests.test_pingora_hwpx_evidence import RUNTIME_BYTES, RUNTIME_TEXT, evaluate_bytes

# The real research artifact from late-life-anxiety-reanalysis#257 (exact head
# 706a81e5a6f88ad74544ab9cf89d4da2b9e6a44d) sits at this path. It is a
# DEFLATE-compressed OOXML package whose first member is [Content_Types].xml,
# with no ZIP comment and no prefixed or appended bytes. The fixtures below
# reproduce that structure without copying another repository's artifact into
# this one; test_real_artifact_bytes_are_admitted binds the same assertion to
# the actual bytes when PINGORA_REAL_DOCX_PATH names a local copy.
REAL_ARTIFACT_PATH = (
    "docs/delivery_interim_20260920/"
    "air_render_00cdc51_g7integration_20260921_205341/manuscript_interim_20260921.docx"
)
REAL_ARTIFACT_ENV = "PINGORA_REAL_DOCX_PATH"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
PACKAGE_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOCUMENT_RELATIONSHIP_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
MAIN_DOCUMENT_CONTENT_TYPE = policy.DOCX_MAIN_DOCUMENT_CONTENT_TYPE
WORD_MAIN_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT_WORD_MAIN_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
# Distinguishes "omit this part entirely" from "use the conforming default".
OMITTED = object()


def content_types_xml(
    *,
    part_name="/word/document.xml",
    content_type=MAIN_DOCUMENT_CONTENT_TYPE,
    overrides=1,
    default_content_type=None,
    root_tag="Types",
    comment="",
):
    """Render one [Content_Types].xml declaration with an exact Override shape."""
    default_extension = (
        f'<Default Extension="xml" ContentType="{default_content_type}"/>'
        if default_content_type is not None
        else '<Default Extension="xml" ContentType="application/xml"/>'
    )
    override = f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
    # An unrelated Override always accompanies the main one, so the part-name
    # filter is exercised in both directions by every positive fixture.
    unrelated = (
        '<Override PartName="/word/settings.xml" ContentType="'
        'application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
    )
    body = default_extension + unrelated + comment + override * overrides
    return f"{XML_DECLARATION}<{root_tag} xmlns=\"{CONTENT_TYPES_NS}\">{body}</{root_tag}>".encode()


def package_rels_xml(
    *,
    target="word/document.xml",
    target_mode=None,
    relationship_type=OFFICE_DOCUMENT_RELATIONSHIP_TYPE,
    relationships=1,
    root_tag="Relationships",
    padding="",
):
    """Render one _rels/.rels package relationship part."""
    mode = f' TargetMode="{target_mode}"' if target_mode is not None else ""
    main = f'<Relationship Id="rId1" Type="{relationship_type}" Target="{target}"{mode}/>'
    # A real package always carries unrelated relationships alongside the
    # officeDocument one, so the relationship-type filter is exercised both ways.
    unrelated = (
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    )
    body = unrelated + main * relationships + padding
    return f"{XML_DECLARATION}<{root_tag} xmlns=\"{PACKAGE_RELATIONSHIPS_NS}\">{body}</{root_tag}>".encode()


def document_xml(*, namespace=WORD_MAIN_NS):
    """Render one minimal but well-formed WordprocessingML main document part."""
    return f'{XML_DECLARATION}<w:document xmlns:w="{namespace}"><w:body/></w:document>'.encode()


def docx_archive(
    *,
    content_types=None,
    package_rels=None,
    document=None,
    compression_type=zipfile.ZIP_DEFLATED,
    duplicate_document=False,
):
    """Create a deterministic, non-sensitive OOXML boundary fixture."""
    archive_buffer = io.BytesIO()
    members = [
        ("[Content_Types].xml", content_types_xml() if content_types is None else content_types),
        ("_rels/.rels", package_rels_xml() if package_rels is None else package_rels),
        ("word/document.xml", document_xml() if document is None else document),
    ]
    if duplicate_document:
        members.append(("word/document.xml", document_xml()))
    with zipfile.ZipFile(archive_buffer, "w") as archive_file:
        for member_name, member_value in members:
            if member_value is OMITTED:
                continue
            member_info = zipfile.ZipInfo(member_name)
            member_info.compress_type = compression_type
            archive_file.writestr(member_info, member_value)
    return archive_buffer.getvalue()


def comment_only_mime_counterexample():
    """Build the reported bypass: the MIME only appears inside an XML comment."""
    return docx_archive(
        content_types=content_types_xml(
            content_type="application/octet-stream",
            comment=f"<!-- {MAIN_DOCUMENT_CONTENT_TYPE} -->",
        ),
        package_rels=b"not xml at all",
        document=b"also not xml",
    )


def deflate_damaged(file_bytes):
    """Corrupt the first compressed stream without touching the ZIP structure."""
    damaged = bytearray(file_bytes)
    data_offset = damaged.find(b"[Content_Types].xml") + len(b"[Content_Types].xml")
    for index in range(data_offset, data_offset + 16):
        damaged[index] ^= 0xFF
    return bytes(damaged)


@pytest.mark.parametrize("file_path", [REAL_ARTIFACT_PATH, "docs/manuscript.docx", "Docs/MANUSCRIPT.DOCX"])
def test_valid_docx_is_admitted_at_the_real_research_artifact_path(file_path):
    """Admit the #257 manuscript by structure, without moving or excluding it."""
    assert evaluate_bytes(file_path, docx_archive()) == ()


@pytest.mark.parametrize("compression_type", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_valid_docx_is_admitted_for_either_stored_or_deflated_parts(compression_type):
    """Real writers DEFLATE every part; stored parts are equally structural."""
    assert evaluate_bytes("docs/manuscript.docx", docx_archive(compression_type=compression_type)) == ()


@pytest.mark.parametrize("target", ["word/document.xml", "/word/document.xml"])
@pytest.mark.parametrize("target_mode", [None, "Internal"])
def test_valid_docx_accepts_either_relationship_target_spelling(target, target_mode):
    """OPC permits both target spellings and an explicit Internal target mode."""
    archive_bytes = docx_archive(package_rels=package_rels_xml(target=target, target_mode=target_mode))
    assert evaluate_bytes("docs/manuscript.docx", archive_bytes) == ()


def test_valid_docx_accepts_the_iso_strict_main_document_namespace():
    """ISO 29500 Strict manuscripts carry the same content type and must pass."""
    archive_bytes = docx_archive(document=document_xml(namespace=STRICT_WORD_MAIN_NS))
    assert evaluate_bytes("docs/manuscript.docx", archive_bytes) == ()


@pytest.mark.skipif(
    not os.environ.get(REAL_ARTIFACT_ENV),
    reason=f"{REAL_ARTIFACT_ENV} must name a local copy of the #257 manuscript",
)
def test_real_artifact_bytes_are_admitted():
    """Bind admission to the actual exact-head bytes, not only to the fixture."""
    with open(os.environ[REAL_ARTIFACT_ENV], "rb") as artifact_file:
        raw = artifact_file.read()
    assert raw.startswith(b"PK\x03\x04")
    assert evaluate_bytes(REAL_ARTIFACT_PATH, raw) == ()


@pytest.mark.parametrize("file_bytes", [
    b"PK\x03\x04\xff",
    docx_archive()[:-10],
    b"#!/bin/sh\n" + RUNTIME_BYTES + docx_archive(),
    b"PK\x03\x04" + docx_archive(),
    docx_archive() + b"\n" + RUNTIME_BYTES,
    docx_archive()[:-2] + b"\x01\x00",
    docx_archive(content_types=b""),
    docx_archive(package_rels=b""),
    docx_archive(document=b""),
    docx_archive(duplicate_document=True),
    deflate_damaged(docx_archive()),
    comment_only_mime_counterexample(),
])
def test_corrupt_or_disguised_docx_container_is_not_exempt(file_bytes):
    """Unreadable, incomplete, or non-structural input still fails closed."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", file_bytes)


@pytest.mark.parametrize("missing_part", ["content_types", "package_rels", "document"])
def test_docx_missing_a_required_opc_part_is_not_exempt(missing_part):
    """Every part in DOCX_REQUIRED_PARTS must actually be present."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", docx_archive(**{missing_part: OMITTED}))


@pytest.mark.parametrize("content_types", [
    # The expected MIME as a Default extension mapping, never as the Override.
    content_types_xml(content_type="application/octet-stream", default_content_type=MAIN_DOCUMENT_CONTENT_TYPE),
    # A spreadsheet package renamed to .docx.
    content_types_xml(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    ),
    # No Override for the main document part at all.
    content_types_xml(overrides=0),
    # Two Overrides for the same part name: an ambiguous declaration.
    content_types_xml(overrides=2),
    # The Override names a different part.
    content_types_xml(part_name="/word/other.xml"),
    # Correct Override, wrong root element.
    content_types_xml(root_tag="Relationships"),
])
def test_docx_requires_an_exact_main_document_content_type_override(content_types):
    """Only an exact Override pairing the main part with its MIME admits."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", docx_archive(content_types=content_types))


@pytest.mark.parametrize("package_rels", [
    # The officeDocument relationship points somewhere else entirely.
    package_rels_xml(target="word/other.xml"),
    # A path traversal target is rejected by exact matching.
    package_rels_xml(target="../../etc/passwd"),
    # An external target is not the packaged main document.
    package_rels_xml(target="https://example.invalid/document.xml", target_mode="External"),
    # No officeDocument relationship at all.
    package_rels_xml(relationships=0),
    # Two officeDocument relationships: an ambiguous package root.
    package_rels_xml(relationships=2),
    # A relationship of a different type cannot stand in for it.
    package_rels_xml(relationship_type="http://schemas.openxmlformats.org/package/2006/relationships/x"),
    # Correct relationship, wrong root element.
    package_rels_xml(root_tag="Types"),
])
def test_docx_requires_the_office_document_relationship_to_agree(package_rels):
    """The package root relationship must resolve to the checked main part."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", docx_archive(package_rels=package_rels))


@pytest.mark.parametrize("part_bytes", [
    b"not xml at all",
    XML_DECLARATION.encode() + b"<Types>",
    b"\xff\xfe<Types/>",
    XML_DECLARATION.encode() + b'<!DOCTYPE Types [<!ENTITY a "b">]><Types/>',
    ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Types/>').encode("utf-16-le"),
    XML_DECLARATION.encode() + b"<Types>&undefined;</Types>",
])
@pytest.mark.parametrize("part_name", ["content_types", "package_rels", "document"])
def test_docx_requires_well_formed_entity_free_xml_parts(part_bytes, part_name):
    """Each required part must be well-formed UTF-8 XML with no DTD or entity."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", docx_archive(**{part_name: part_bytes}))


@pytest.mark.parametrize("part_name, padding_length", [
    ("content_types", policy.MAX_DOCX_CONTENT_TYPES_BYTES + 1),
    ("package_rels", policy.MAX_DOCX_CONTENT_TYPES_BYTES + 1),
    ("document", policy.MAX_DOCX_MAIN_PART_BYTES + 1),
])
def test_oversized_docx_part_is_not_read_beyond_its_ceiling(part_name, padding_length):
    """A part beyond its bounded read ceiling is rejected, never streamed."""
    padding = "<!--" + "p" * padding_length + "-->"
    if part_name == "content_types":
        part_bytes = content_types_xml(comment=padding)
    elif part_name == "package_rels":
        part_bytes = package_rels_xml(padding=padding)
    else:
        part_bytes = document_xml()[:-len(b"</w:document>")] + padding.encode() + b"</w:document>"
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", docx_archive(**{part_name: part_bytes}))


def test_docx_rejects_an_encrypted_or_entryless_package():
    """An encrypted part or an empty central directory is unverifiable, so it fails."""
    encrypted_bytes = bytearray(docx_archive())
    encrypted_bytes[encrypted_bytes.find(b"PK\x01\x02") + 8] |= 1
    entryless_bytes = bytearray(docx_archive())
    end_offset = len(entryless_bytes) - 22
    entryless_bytes[end_offset + 8:end_offset + 12] = b"\x00\x00\x00\x00"
    entryless_bytes[end_offset + 12:end_offset + 16] = b"\x00\x00\x00\x00"
    entryless_bytes[end_offset + 16:end_offset + 20] = end_offset.to_bytes(4, "little")
    for file_bytes in (bytes(encrypted_bytes), bytes(entryless_bytes)):
        with pytest.raises(policy.PolicyError):
            evaluate_bytes("docs/manuscript.docx", file_bytes)


@pytest.mark.parametrize("file_path", ["docs/manuscript.docx", "local/model.zip"])
def test_non_utf8_bytes_without_a_structural_document_still_fail(file_path):
    """Opaque bytes that are not a recognized structural document are never admitted."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes(file_path, b"\x00\x01\x02\xff\xfe" + RUNTIME_BYTES)


@pytest.mark.parametrize("patch_value", [None, "+" + RUNTIME_TEXT.rstrip("\n")])
def test_valid_utf8_named_docx_keeps_todays_runtime_scan(patch_value):
    """A file that decodes as UTF-8 is never treated as a binary artifact."""
    violations = evaluate_bytes("docs/manuscript.docx", RUNTIME_BYTES, patch_value=patch_value)
    assert [violation.rule for violation in violations] == ["nginx_runtime_path"]


def test_docx_in_runtime_path_remains_unavailable():
    """A structural format exception cannot exempt an active runtime location."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/nginx/manuscript.docx", docx_archive())


def test_removed_docx_does_not_load_deleted_content():
    """Deletion does not require unavailable final-head bytes."""
    assert evaluate_bytes("docs/manuscript.docx", b"", file_status="removed") == ()
