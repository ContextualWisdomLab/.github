"""Exercise HWPX admission through the production policy boundary offline."""
import base64
import io
import zipfile

import pytest
from tests.test_pingora_edge_policy import policy


def hwpx_archive(*, mime_value=b"application/hwp+zip", manifest_value=b"<package/>", compression_type=zipfile.ZIP_STORED):
    """Create a deterministic, non-sensitive format-boundary fixture."""
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive_file:
        mime_info = zipfile.ZipInfo("mimetype")
        mime_info.compress_type = compression_type
        archive_file.writestr(mime_info, mime_value)
        if manifest_value is not None:
            archive_file.writestr(zipfile.ZipInfo("Contents/content.hpf"), manifest_value)
    return archive_buffer.getvalue()


def evaluate_bytes(file_path, file_bytes, *, patch_value=None, file_status="added"):
    """Supply only in-memory GitHub metadata and exact-head content."""
    def open_evidence(request_url, request_token):
        assert request_token == "offline-fixture"
        if "/files?" in request_url:
            file_entry = {"filename": file_path, "status": file_status}
            if patch_value is not None:
                file_entry["patch"] = patch_value
            return [file_entry]
        assert "?ref=" + "a" * 40 in request_url
        return {"type": "file", "encoding": "base64", "size": len(file_bytes),
                "content": base64.b64encode(file_bytes).decode("ascii")}
    return policy.evaluate_pull_request(api_url="https://api.github.com",
        repository="ContextualWisdomLab/example", pull_request=2116, head_sha="a" * 40,
        event_action="opened", token="offline-fixture", opener=open_evidence)


@pytest.mark.parametrize("file_path", ["evidence/reviewer_response_draft.hwpx", "docs/paper.hwpx", "Evidence/PAPER.HWPX"])
def test_valid_hwpx_is_admitted_at_document_and_consumer_paths(file_path):
    """Recognize HWPX at the exact consumer directory, without renaming it."""
    assert evaluate_bytes(file_path, hwpx_archive()) == ()


@pytest.mark.parametrize("file_bytes", [
    b"PK\x03\x04\xff", hwpx_archive()[:-10],
    b"#!/bin/sh\ncat /etc/nginx/nginx.conf\n" + hwpx_archive(),
    hwpx_archive() + b"\ncat /etc/nginx/nginx.conf\n",
    hwpx_archive(mime_value=b"application/zip"),
    hwpx_archive(manifest_value=None), hwpx_archive(manifest_value=b""),
    hwpx_archive(compression_type=zipfile.ZIP_DEFLATED),
])
def test_malformed_or_disguised_archive_is_not_exempt(file_bytes):
    """Unsupported format evidence fails closed instead of bypassing scanning."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("evidence/reviewer_response_draft.hwpx", file_bytes)


@pytest.mark.parametrize("file_path", ["evidence/paper.hwpx", "docs/paper.hwpx", "scripts/paper.hwpx"])
@pytest.mark.parametrize("patch_value", [None, "+cat /etc/nginx/nginx.conf"])
def test_text_renamed_to_hwpx_preserves_runtime_scan(file_path, patch_value):
    """Neither the suffix nor patch absence hides actual Nginx runtime text."""
    violations = evaluate_bytes(file_path, b"cat /etc/nginx/nginx.conf\n", patch_value=patch_value)
    assert [violation.rule for violation in violations] == ["nginx_runtime_path"]


def test_hwpx_does_not_expand_text_document_exemptions():
    """The consumer evidence directory does not exempt ordinary configuration."""
    violations = evaluate_bytes("evidence/config.txt", b"cat /etc/nginx/nginx.conf\n")
    assert [violation.rule for violation in violations] == ["nginx_runtime_path"]


def test_hwpx_in_runtime_path_remains_unavailable():
    """A format exception cannot exempt an active runtime location."""
    with pytest.raises(policy.PolicyError):
        evaluate_bytes("docs/nginx/paper.hwpx", hwpx_archive())


def test_removed_hwpx_does_not_load_deleted_content():
    """Deletion does not require unavailable final-head bytes."""
    assert evaluate_bytes("evidence/paper.hwpx", b"", file_status="removed") == ()


def test_hwpx_rejects_inconsistent_comment_and_shifted_zip():
    """EOCD declarations and member offsets must bind to the actual bytes."""
    archive_bytes = hwpx_archive()
    invalid_comment = archive_bytes[:-2] + b"\x01\x00"
    for file_bytes in (invalid_comment, b"PK\x03\x04" + archive_bytes):
        with pytest.raises(policy.PolicyError):
            evaluate_bytes("evidence/paper.hwpx", file_bytes)


def test_hwpx_rejects_nonfirst_marker_and_encrypted_manifest():
    """A named marker alone cannot admit a reordered or encrypted package."""
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive_file:
        archive_file.writestr(zipfile.ZipInfo("Contents/content.hpf"), b"<package/>")
        archive_file.writestr(zipfile.ZipInfo("mimetype"), b"application/hwp+zip")
    encrypted_bytes = bytearray(hwpx_archive())
    manifest_header = encrypted_bytes.rfind(b"PK\x01\x02")
    encrypted_bytes[manifest_header + 8] |= 1
    for file_bytes in (archive_buffer.getvalue(), bytes(encrypted_bytes)):
        with pytest.raises(policy.PolicyError):
            evaluate_bytes("evidence/paper.hwpx", file_bytes)
