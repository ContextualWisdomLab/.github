"""Exercise DOCX structural admission through the production policy boundary offline."""
import io
import zipfile

import pytest
from tests.test_pingora_edge_policy import policy
from tests.test_pingora_hwpx_evidence import RUNTIME_BYTES, RUNTIME_TEXT, evaluate_bytes

# The real research artifact from late-life-anxiety-reanalysis#257 (exact head
# 706a81e5a6f88ad74544ab9cf89d4da2b9e6a44d) sits at this path. It is a
# DEFLATE-compressed OOXML package whose first member is [Content_Types].xml,
# with no ZIP comment and no prefixed or appended bytes. The fixture below
# reproduces exactly that structure without copying another repository's
# artifact into this one.
REAL_ARTIFACT_PATH = (
    "docs/delivery_interim_20260920/"
    "air_render_00cdc51_g7integration_20260921_205341/manuscript_interim_20260921.docx"
)
MAIN_DOCUMENT_CONTENT_TYPE = (
    b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
CONTENT_TYPES_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    b'<Override PartName="/word/document.xml" ContentType="' + MAIN_DOCUMENT_CONTENT_TYPE + b'"/>'
    b"</Types>"
)
SPREADSHEET_CONTENT_TYPES_XML = CONTENT_TYPES_XML.replace(
    MAIN_DOCUMENT_CONTENT_TYPE,
    b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
)


def docx_archive(
    *,
    content_types=CONTENT_TYPES_XML,
    package_rels=b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
    document=b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
    compression_type=zipfile.ZIP_DEFLATED,
    duplicate_document=False,
):
    """Create a deterministic, non-sensitive OOXML boundary fixture."""
    archive_buffer = io.BytesIO()
    members = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", package_rels),
        ("word/document.xml", document),
    ]
    if duplicate_document:
        members.append(("word/document.xml", document))
    with zipfile.ZipFile(archive_buffer, "w") as archive_file:
        for member_name, member_value in members:
            if member_value is None:
                continue
            member_info = zipfile.ZipInfo(member_name)
            member_info.compress_type = compression_type
            archive_file.writestr(member_info, member_value)
    return archive_buffer.getvalue()


@pytest.mark.parametrize("file_path", [REAL_ARTIFACT_PATH, "docs/manuscript.docx", "Docs/MANUSCRIPT.DOCX"])
def test_valid_docx_is_admitted_at_the_real_research_artifact_path(file_path):
    """Admit the #257 manuscript by structure, without moving or excluding it."""
    assert evaluate_bytes(file_path, docx_archive()) == ()


@pytest.mark.parametrize("compression_type", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_valid_docx_is_admitted_for_either_stored_or_deflated_parts(compression_type):
    """Real writers DEFLATE every part; stored parts are equally structural."""
    assert evaluate_bytes("docs/manuscript.docx", docx_archive(compression_type=compression_type)) == ()


@pytest.mark.parametrize("file_bytes", [
    b"PK\x03\x04\xff",
    docx_archive()[:-10],
    b"#!/bin/sh\n" + RUNTIME_BYTES + docx_archive(),
    docx_archive() + b"\n" + RUNTIME_BYTES,
    docx_archive()[:-2] + b"\x01\x00",
    docx_archive(content_types=None),
    docx_archive(package_rels=None),
    docx_archive(document=None),
    docx_archive(document=b""),
    docx_archive(content_types=SPREADSHEET_CONTENT_TYPES_XML),
    docx_archive(duplicate_document=True),
])
def test_corrupt_or_disguised_docx_container_is_not_exempt(file_bytes):
    """Unreadable, incomplete, or non-WordprocessingML input still fails closed."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", file_bytes)


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


def test_oversized_content_types_declaration_is_not_read():
    """A declaration beyond the bounded read ceiling is rejected, never streamed."""
    padding = b"<!--" + b"p" * (policy.MAX_DOCX_CONTENT_TYPES_BYTES + 1) + b"-->"
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/manuscript.docx", docx_archive(content_types=CONTENT_TYPES_XML + padding))


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
