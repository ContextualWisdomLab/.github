"""Regression tests for the organization-wide Pingora edge policy."""

from __future__ import annotations

import base64
import importlib.util
import inspect
import re
import sys
import zlib
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "ci" / "pingora_edge_policy.py"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pingora_policy_samples.txt"
SPEC = importlib.util.spec_from_file_location("pingora_edge_policy", MODULE_PATH)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def fixture_text() -> str:
    """Return the dedicated source sample used to exercise denied runtime forms."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


def encoded_file(content: str, *, size: int | None = None, kind: str = "file", encoding: str = "base64") -> dict[str, object]:
    """Build one GitHub Contents API response."""

    raw = content.encode()
    return {
        "type": kind,
        "encoding": encoding,
        "size": len(raw) if size is None else size,
        "content": base64.b64encode(raw).decode(),
    }


def test_scan_content_rejects_runtime_paths_and_every_denied_runtime_form() -> None:
    """Runtime filenames and all supported active Nginx forms fail closed."""

    content = fixture_text()
    violations = policy.scan_content("infra/nginx/nginx.conf", content)
    rules = {item.rule for item in violations}
    assert rules == {
        "nginx_runtime_artifact",
        "nginx_container_image",
        "nginx_ingress_controller",
        "nginx_runtime_command",
        "nginx_runtime_path",
        "nginx_package_install",
    }
    assert all(item.line >= 1 and item.excerpt for item in violations)


def test_scan_content_allows_prose_license_and_source_negative_fixtures() -> None:
    """Policy prose, license text, and scanner source fixtures can name Nginx."""

    sample = fixture_text()
    assert policy.scan_content("docs/migration.md", sample) == ()
    assert policy.scan_content("COPYING", sample) == ()
    assert policy.scan_content("scripts/ci/pingora_edge_policy.py", sample) == ()
    assert policy.scan_content("tests/test_pingora_edge_policy.py", sample) == ()
    assert policy.scan_content("tests/fixtures/policy_samples.py", sample) == ()
    assert policy.scan_content("tests/fixtures/negative_fixture.rs", sample) == ()
    assert policy.scan_content("deploy/fixtures/runtime.yaml", sample)
    assert policy.scan_content(
        "deploy/monitoring.yaml", "image: nginx/nginx-prometheus-exporter:1.0\n"
    ) == ()
    assert policy.scan_content(
        "deploy/ingress.yaml", "image: nginx/nginx-ingress:1.11\n"
    )


def test_this_test_files_own_content_is_exempt() -> None:
    """This file's own fixture strings (denied Nginx forms) must never self-trip.

    Regression coverage for a real required-workflow-bootstrap failure: a
    diff to this file that happens to add a line matching a CONTENT_RULES
    pattern (e.g. a new test fixture containing "/etc/nginx/") triggers
    _needs_content_scan's "nginx" in the patch heuristic, which then scans
    this file's *entire* current content -- full of intentional denied
    forms by design -- unless this exact path is self-exempted the same way
    scripts/ci/pingora_edge_policy.py already is.
    """

    own_content = Path(__file__).read_text(encoding="utf-8")
    assert policy.scan_content("tests/test_pingora_edge_policy.py", own_content) == ()


def test_nested_documentation_path_allows_prose_samples() -> None:
    """Documentation directories remain exempt when nested below a package."""

    assert policy.scan_content("packages/component/docs/migration.md", fixture_text()) == ()


def test_needs_content_scan_exempts_documentation_pdfs() -> None:
    """A cited research-paper PDF under docs/ never reaches content scanning.

    Binary files never carry a GitHub diff `patch`, so without this exemption
    `_needs_content_scan` falls through to its `not patch_available` branch and
    always returns True for a PDF -- and any such file over the Contents API's
    1 MiB base64 ceiling then fails closed in `_load_file_content` for a
    reason unrelated to the Nginx runtime policy this module enforces (see
    this org's "attach the relevant paper PDF under docs/papers/" convention).
    """

    changed = policy.ChangedFile
    assert not policy._needs_content_scan(
        changed("docs/papers/helm-holistic-evaluation-2211.09110.pdf", "added", "", patch_available=False)
    )
    assert not policy._needs_content_scan(
        changed("docs/papers/README.md", "modified", "", patch_available=False)
    )
    # A PDF outside a recognized documentation directory is not exempted --
    # only prose/paper locations are trusted to be inert.
    assert policy._needs_content_scan(
        changed("scripts/ci/payload.pdf", "added", "", patch_available=False)
    )


def test_needs_content_scan_still_inspects_a_textual_pdf_with_a_patch() -> None:
    """A '.pdf'-suffixed file GitHub *can* diff is not the binary case exempted.

    GitHub never returns a diff `patch` for a true binary file, so
    `patch_available=True` here means this file is textual despite its
    suffix -- exactly the case that could smuggle an active Nginx runtime
    artifact under a docs/ path if the PDF exemption were suffix-only rather
    than gated on patch availability.
    """

    changed = policy.ChangedFile
    assert policy._needs_content_scan(
        changed(
            "docs/papers/not-really-a-pdf.pdf",
            "added",
            "+load_module modules/ngx_http_nginx_module.so;",
            patch_available=True,
        )
    )


@pytest.mark.parametrize("directory", ["testing", "contests", "assert", "my_tests"])
def test_scan_content_does_not_treat_test_name_substrings_as_fixtures(
    directory: str,
) -> None:
    """Only exact test directories are fixture boundaries for active content."""

    violations = policy.scan_content(
        f"{directory}/runtime.py",
        "FROM nginx:1.27-alpine\n",
    )

    assert [item.rule for item in violations] == ["nginx_container_image"]


def test_runtime_path_rule_covers_script_and_config_shapes() -> None:
    """Active Nginx filenames are blocked without relying on their contents."""

    assert policy._runtime_path_rule("tests/live/nginx.conf") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("ops/nginx-backup.sh") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("infra/nginx/default.yaml") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("config/nginx/default.conf") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("config/nginx.service") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("docs/nginx-history.md") is None


def test_needs_content_scan_is_delta_bounded() -> None:
    """Removed/prose files skip, while bounded runtime candidates always scan."""

    changed = policy.ChangedFile
    assert not policy._needs_content_scan(changed("Dockerfile", "removed", "+FROM nginx"))
    assert not policy._needs_content_scan(changed("README.md", "modified", "+nginx"))
    assert policy._needs_content_scan(changed("Dockerfile", "modified", "-FROM nginx\n+FROM scratch"))
    assert policy._needs_content_scan(changed("config/runtime.txt", "modified", "+FROM nginx"))
    assert policy._needs_content_scan(changed("infra/nginx/default.yaml", "modified", "+server: edge"))
    assert policy._needs_content_scan(changed("kubernetes/ingress.yaml", "modified", "+metadata: edge"))
    assert policy._needs_content_scan(changed("ops/edge.yaml", "modified", "+metadata: edge"))
    assert policy._needs_content_scan(changed("infra/deployment.yaml", "modified", "+image: app"))
    assert policy._needs_content_scan(changed("manifests/ingress.yaml", "modified", "+metadata: edge"))
    assert policy._needs_content_scan(changed("config/runtime.conf", "modified", "+upstream nginx"))
    assert policy._needs_content_scan(
        changed("config/runtime.conf", "modified", "", patch_available=False)
    )
    assert policy._needs_content_scan(changed("config/runtime.conf", "modified", "+upstream app"))
    assert policy._needs_content_scan(changed("src/runtime.go", "modified", "+exec nginx"))
    assert not policy._needs_content_scan(changed("src/runtime.go", "modified", "+exec pingora"))


def test_active_test_source_is_scanned_while_dedicated_fixtures_are_exempt() -> None:
    """Executable test helpers remain candidates; only explicit fixtures are exempt."""

    violations = policy.scan_content("tests/e2e/start_nginx.py", "systemctl restart nginx\n")
    assert [item.rule for item in violations] == ["nginx_runtime_command"]


def test_source_identifier_is_not_an_nginx_command() -> None:
    """A source-language function name is not an executable shell launch."""

    assert policy.scan_content("src/runtime.py", "nginx()\n") == ()


def test_sudo_options_are_supported_for_runtime_commands_and_packages() -> None:
    """Bounded sudo flags cannot hide prohibited Nginx operations."""

    violations = policy.scan_content(
        "src/runtime.sh", "sudo -n nginx -s reload\nsudo -n apt-get install nginx\n"
    )
    assert {item.rule for item in violations} == {
        "nginx_runtime_command",
        "nginx_package_install",
    }


def test_sudo_argument_options_do_not_reinterpret_their_values() -> None:
    """Sudo user values do not become false Nginx commands."""

    violations = policy.scan_content(
        "src/runtime.sh",
        "sudo -u nginx php-fpm\nsudo -u root nginx -s reload\n"
        "sudo --user root apt-get install nginx\n",
    )
    assert {item.rule for item in violations} == {
        "nginx_runtime_command",
        "nginx_package_install",
    }


def test_untrusted_document_suffix_does_not_bypass_runtime_scan() -> None:
    """A runtime-looking file cannot evade policy checks by using a prose suffix."""

    violations = policy.scan_content("config/runtime.txt", "FROM nginx:1.27-alpine\n")
    assert [item.rule for item in violations] == ["nginx_container_image"]


def test_evaluate_pull_request_reads_pagination_and_final_content() -> None:
    """The checker uses every file page and scans final head content, not removed lines."""

    calls: list[str] = []
    first_page = [
        {"filename": f"docs/file-{index}.md", "status": "modified", "patch": "+Nginx"}
        for index in range(100)
    ]
    second_page = [
        {"filename": "Dockerfile", "status": "modified", "patch": "-FROM nginx\n+FROM scratch"},
        {"filename": "old/nginx.conf", "status": "removed", "patch": "-server {}"},
        {"filename": "deploy/proxy.yaml", "status": "modified"},
    ]

    def opener(url: str, token: str) -> object:
        calls.append(url)
        assert token == "token"
        if url.endswith("page=1"):
            return first_page
        if url.endswith("page=2"):
            return second_page
        if "/contents/Dockerfile" in url:
            return encoded_file("FROM scratch\n")
        if "/contents/deploy/proxy.yaml" in url:
            return encoded_file("image: cwl-pingora-proxy:0.1.0\n")
        raise AssertionError(url)

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test/",
        repository="ContextualWisdomLab/example",
        pull_request=7,
        head_sha="a" * 40,
        event_action="synchronize",
        token="token",
        opener=opener,
    )
    assert result == ()
    assert any("page=2" in url for url in calls)
    assert all("old/nginx.conf" not in url for url in calls)


def test_evaluate_pull_request_reports_final_runtime_violation() -> None:
    """A changed active runtime image is rejected from final head content."""

    def opener(url: str, _token: str) -> object:
        if "/pulls/9/files" in url:
            return [{"filename": "docker-compose.yml", "status": "modified", "patch": "+image: nginx"}]
        return encoded_file("services:\n  edge:\n    image: nginx:1.27-alpine\n")

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=9,
        head_sha="b" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert [item.rule for item in result] == ["nginx_container_image"]


def test_evaluate_pull_request_exempts_an_oversized_documentation_pdf() -> None:
    """A genuinely oversized documentation PDF still cannot be verified by content.

    GitHub's real Contents API response for a file whose blob exceeds the
    inline-content ceiling reports ``encoding: "none"`` with an accurate
    ``size`` and no ``content`` at all (not a ``base64``-encoded entry with
    an oversized declared size) -- this is that real shape, not a synthetic
    one, per Devin Review's finding that the earlier version of this test
    used a response shape GitHub never actually returns. This is the one
    case that still falls back to the path+suffix convention -- the real
    research-paper-citation use case this whole exemption exists for.
    """

    def opener(url: str, _token: str) -> object:
        if "/pulls/11/files" in url:
            return [
                {"filename": "docs/papers/big-paper.pdf", "status": "added"},
            ]
        assert "/contents/docs/papers/big-paper.pdf" in url
        return {"type": "file", "encoding": "none", "size": policy.MAX_FILE_BYTES + 1, "content": ""}

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=11,
        head_sha="c" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert result == ()


def test_evaluate_pull_request_scans_a_disguised_textual_pdf_without_a_patch() -> None:
    """A patchless '.pdf' file that fetches as real content is still scanned.

    Regression coverage for Devin Review's second finding: a missing diff
    patch is not proof of binary content by itself (GitHub also omits one
    for a textual diff over its own rendering limit, well under this
    module's MAX_FILE_BYTES fetch ceiling), so a file this small must be
    verified by its real magic bytes, not trusted on patch-absence alone.
    """

    def opener(url: str, _token: str) -> object:
        if "/pulls/12/files" in url:
            return [
                {"filename": "docs/papers/not-really-a-pdf.pdf", "status": "added"},
            ]
        assert "/contents/docs/papers/not-really-a-pdf.pdf" in url
        return encoded_file("cat /etc/nginx/nginx.conf\n")

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=12,
        head_sha="d" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert [item.rule for item in result] == ["nginx_runtime_path"]


def test_evaluate_pull_request_exempts_a_real_pdf_under_the_size_ceiling() -> None:
    """A genuine, fetchable PDF (verified by its magic bytes) is exempt too."""

    def opener(url: str, _token: str) -> object:
        if "/pulls/13/files" in url:
            return [
                {"filename": "docs/papers/small-paper.pdf", "status": "added"},
            ]
        assert "/contents/docs/papers/small-paper.pdf" in url
        return encoded_file("%PDF-1.7\nupstream nginx { server 127.0.0.1:9; }\n")

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=13,
        head_sha="e" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert result == ()


def test_evaluate_pull_request_exempts_a_real_documentation_png() -> None:
    """A screenshot is verified by PNG magic instead of decoded as UTF-8."""

    def opener(url: str, _token: str) -> object:
        if "/pulls/15/files" in url:
            return [{"filename": "docs/screenshots/dashboard.png", "status": "added"}]
        assert "/contents/docs/screenshots/dashboard.png" in url
        raw = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        return {
            "type": "file",
            "encoding": "base64",
            "size": len(raw),
            "content": base64.b64encode(raw).decode("ascii"),
        }

    assert policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=15,
        head_sha="a" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    ) == ()


def test_evaluate_pull_request_rejects_a_fake_documentation_png() -> None:
    """A PNG suffix without PNG magic remains runtime-content evidence."""

    def opener(url: str, _token: str) -> object:
        if "/pulls/16/files" in url:
            return [{"filename": "docs/screenshots/fake.png", "status": "added"}]
        return encoded_file("cat /etc/nginx/nginx.conf\n")

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=16,
        head_sha="b" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert [item.rule for item in result] == ["nginx_runtime_path"]


def test_evaluate_pull_request_rejects_png_with_appended_runtime_text() -> None:
    """A valid image prefix cannot hide bytes appended after the IEND chunk."""

    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )

    def opener(url: str, _token: str) -> object:
        if "/pulls/17/files" in url:
            return [{"filename": "docs/screenshots/forged.png", "status": "added"}]
        raw = image + b"\ncat /etc/nginx/nginx.conf\n"
        return {
            "type": "file", "encoding": "base64", "size": len(raw),
            "content": base64.b64encode(raw).decode("ascii"),
        }

    with pytest.raises(policy.PolicyError, match="not valid UTF-8"):
        policy.evaluate_pull_request(
            api_url="https://api.github.test",
            repository="ContextualWisdomLab/example",
            pull_request=17,
            head_sha="c" * 40,
            event_action="opened",
            token="token",
            opener=opener,
        )


def test_png_structure_validation_fails_closed_on_malformed_chunks() -> None:
    """Every malformed PNG boundary returns false without parsing past bounds."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return len(data).to_bytes(4, "big") + payload + zlib.crc32(payload).to_bytes(4, "big")

    signature = policy.PNG_SIGNATURE
    header = chunk(b"IHDR", b"\0" * 13)
    assert not policy._is_complete_png(b"not-png")
    assert not policy._is_complete_png(signature)
    assert not policy._is_complete_png(
        signature + (99).to_bytes(4, "big") + b"IHDR" + b"\0" * 4
    )
    assert not policy._is_complete_png(signature + header[:-1] + b"\0")
    assert not policy._is_complete_png(signature + chunk(b"TEXT", b""))
    assert not policy._is_complete_png(signature + header + chunk(b"IEND", b""))
    assert not policy._is_complete_png(signature + header + chunk(b"TEXT", b""))


def test_png_semantic_validation_fails_closed() -> None:
    """CRC-valid chunks still need a valid bounded PNG image stream."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        payload = kind + data
        return len(data).to_bytes(4, "big") + payload + zlib.crc32(payload).to_bytes(4, "big")

    def png(header: bytes, *chunks: bytes) -> bytes:
        return policy.PNG_SIGNATURE + chunk(b"IHDR", header) + b"".join(chunks)

    def indexed_png(
        width: int,
        height: int,
        bit_depth: int,
        palette_entries: int,
        decoded: bytes,
        *,
        interlace: int = 0,
    ) -> bytes:
        header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes((bit_depth, 3, 0, 0, interlace))
        return png(
            header,
            chunk(b"PLTE", b"\0\0\0" * palette_entries),
            chunk(b"IDAT", zlib.compress(decoded)),
            chunk(b"IEND", b""),
        )

    rgba = (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 0))
    indexed = (1).to_bytes(4, "big") * 2 + bytes((8, 3, 0, 0, 0))
    gray = (1).to_bytes(4, "big") * 2 + bytes((8, 0, 0, 0, 0))
    image = chunk(b"IDAT", zlib.compress(b"\0\0\0\0\0"))
    end = chunk(b"IEND", b"")

    invalid_headers = (
        b"\0" * 13,
        (1).to_bytes(4, "big") * 2 + bytes((4, 2, 0, 0, 0)),
        (1).to_bytes(4, "big") * 2 + bytes((8, 6, 1, 0, 0)),
        (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 1, 0)),
        (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 2)),
    )
    assert all(not policy._is_complete_png(png(header, image, end)) for header in invalid_headers)
    assert not policy._is_complete_png(png(rgba, chunk(b"IHDR", rgba), image, end))
    assert not policy._is_complete_png(png(rgba, chunk(b"PLTE", b""), image, end))
    assert not policy._is_complete_png(png(rgba, chunk(b"PLTE", b"x" * 769), image, end))
    assert not policy._is_complete_png(png(rgba, chunk(b"PLTE", b"x"), image, end))
    assert not policy._is_complete_png(png(rgba, chunk(b"1EXt", b""), image, end))
    assert not policy._is_complete_png(png(rgba, chunk(b"tExt", b""), image, end))
    assert not policy._is_complete_png(png(rgba, chunk(b"ABCD", b""), image, end))
    assert policy._is_complete_png(png(rgba, chunk(b"tEXt", b"x"), image, end))
    assert not policy._is_complete_png(png(rgba, image, chunk(b"tEXt", b"x"), image, end))
    assert not policy._is_complete_png(png(indexed, image, end))
    indexed_one_bit = (1).to_bytes(4, "big") * 2 + bytes((1, 3, 0, 0, 0))
    assert not policy._is_complete_png(
        png(indexed_one_bit, chunk(b"PLTE", b"\0" * 9), chunk(b"IDAT", zlib.compress(b"\0\0")), end)
    )
    for filter_type in range(5):
        second_row = b"\1\0" if filter_type == 0 else b"\1\xff"
        assert policy._is_complete_png(
            indexed_png(2, 2, 8, 2, bytes((filter_type, 0, 1, filter_type)) + second_row)
        )
    assert not policy._is_complete_png(indexed_png(2, 1, 8, 1, b"\0\0\1"))
    assert not policy._is_complete_png(indexed_png(2, 2, 8, 2, b"\0\0\1\4\2\xfe"))
    assert policy._is_complete_png(indexed_png(2, 1, 1, 2, b"\0\x40"))
    assert not policy._is_complete_png(indexed_png(2, 1, 1, 1, b"\0\x40"))
    assert policy._is_complete_png(indexed_png(1, 1, 8, 1, b"\0\0", interlace=1))
    assert not policy._is_complete_png(indexed_png(1, 1, 8, 1, b"\0\1", interlace=1))
    assert not policy._is_complete_png(png(gray, chunk(b"PLTE", b"\0\0\0"), chunk(b"IDAT", zlib.compress(b"\0\0")), end))
    assert not policy._is_complete_png(png(rgba, chunk(b"IDAT", b"not-zlib"), end))
    assert not policy._is_complete_png(png(rgba, chunk(b"IDAT", zlib.compress(b"\0")), end))
    assert not policy._is_complete_png(png(rgba, chunk(b"IDAT", zlib.compress(b"\0\0\0\0\0") + b"x"), end))
    assert not policy._is_complete_png(png(rgba, chunk(b"IDAT", zlib.compress(b"\5\0\0\0\0")), end))
    huge = (policy.MAX_RESPONSE_BYTES).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes((8, 6, 0, 0, 0))
    assert not policy._is_complete_png(png(huge, image, end))

    adam7 = (8).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 1))
    adam7_scanlines = b"".join(
        b"\0" + b"\0" * (pass_width * 4)
        for pass_width, pass_height in ((1, 1), (1, 1), (2, 1), (2, 2), (4, 2), (4, 4), (8, 4))
        for _ in range(pass_height)
    )
    assert policy._is_complete_png(
        png(adam7, chunk(b"IDAT", zlib.compress(adam7_scanlines)), end)
    )
    adam7_one_pixel = (1).to_bytes(4, "big") * 2 + bytes((8, 6, 0, 0, 1))
    assert policy._is_complete_png(
        png(adam7_one_pixel, chunk(b"IDAT", zlib.compress(b"\0\0\0\0\0")), end)
    )


def test_evaluate_pull_request_does_not_fetch_a_removed_binary_pdf() -> None:
    """A removed documentation PDF has no head content to fetch at all.

    Regression coverage for Devin Review's finding: _is_binary_documentation_asset
    does not itself check status, so without an explicit removed-status guard
    in evaluate_pull_request's own loop, a deleted PDF would try to fetch its
    (nonexistent) head content and fail evidence collection for every such
    deletion.
    """

    def opener(url: str, _token: str) -> object:
        if "/pulls/14/files" in url:
            return [
                {"filename": "docs/papers/removed-paper.pdf", "status": "removed"},
            ]
        raise AssertionError(f"must not fetch content for a removed file: {url}")

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=14,
        head_sha="f" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert result == ()


def test_closed_event_skips_without_credentials_or_identity_validation() -> None:
    """Closed-event cleanup remains a no-op for the required-workflow context."""

    assert policy.evaluate_pull_request(
        api_url="x",
        repository="bad repo",
        pull_request=0,
        head_sha="bad",
        event_action="closed",
        token="",
        opener=lambda _url, _token: pytest.fail("must not open"),
    ) == ()


@pytest.mark.parametrize(
    ("repository", "pull_request", "head_sha", "token", "message"),
    [
        ("bad repo", 1, "a" * 40, "x", "Repository identity"),
        ("a/b", 0, "a" * 40, "x", "must be positive"),
        ("a/b", 1, "bad", "x", "head SHA"),
        ("a/b", 1, "a" * 40, "", "GITHUB_TOKEN"),
    ],
)
def test_evaluate_pull_request_rejects_invalid_authority(
    repository: str, pull_request: int, head_sha: str, token: str, message: str
) -> None:
    """Malformed authority and absent credentials fail before network access."""

    with pytest.raises(policy.PolicyError, match=message):
        policy.evaluate_pull_request(
            api_url="x",
            repository=repository,
            pull_request=pull_request,
            head_sha=head_sha,
            event_action="opened",
            token=token,
            opener=lambda _url, _token: pytest.fail("must not open"),
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "not a JSON array"),
        (["bad"], "entry is not an object"),
        ([{"filename": "", "status": "modified", "patch": ""}], "invalid bounded fields"),
    ],
)
def test_changed_file_evidence_shape_is_fail_closed(payload: object, message: str) -> None:
    """Malformed changed-file API shapes fail closed."""

    with pytest.raises(policy.PolicyError, match=message):
        policy._load_changed_files("api", "a/b", 1, "x", lambda _url, _token: payload)


def test_changed_file_pagination_bound_is_fail_closed() -> None:
    """More than 3,000 changed files cannot silently truncate policy evidence."""

    page = [{"filename": f"f-{index}", "status": "modified", "patch": ""} for index in range(100)]
    with pytest.raises(policy.PolicyError, match="3,000"):
        policy._load_changed_files("api", "a/b", 1, "x", lambda _url, _token: page)


def test_changed_file_pagination_accepts_the_inclusive_bound() -> None:
    """Exactly 3,000 changed files are accepted only after an empty next page."""

    page = [
        {"filename": f"f-{index}", "status": "modified", "patch": ""}
        for index in range(100)
    ]
    calls: list[str] = []

    def opener(url: str, _token: str) -> object:
        calls.append(url)
        return page if "page=31" not in url else []

    files = policy._load_changed_files("api", "a/b", 1, "x", opener)
    assert len(files) == 3_000
    assert calls[-1].endswith("page=31")


def test_changed_file_pagination_bound_is_provably_unreachable() -> None:
    """Pin the arithmetic invariant that makes the loop's trailing raise dead code.

    ``_load_changed_files`` raises inside its item loop the moment
    ``len(files) > 3_000`` (checked after every appended item, not only at
    page boundaries) and returns early the moment one page has fewer than
    100 items -- so the ``# pragma: no cover``-marked ``raise`` after the
    ``for page in range(...)`` loop can only execute if every one of that
    many pages returns at least 100 items while the cumulative total never
    exceeds 3,000. That requires ``page_count * per_page <= 3_000``, which
    the real page count (31) and per_page (100) violate (3,100 > 3,000) --
    the in-loop raise always fires first. This test reads those literals
    from the actual source rather than duplicating them, so it fails loudly
    if a future edit to any of the three breaks the inequality -- exactly
    when the trailing raise becomes reachable again and needs a real
    covering test instead of the pragma.
    """
    source = inspect.getsource(policy._load_changed_files)
    start, stop = (int(n) for n in re.search(r"range\((\d+),\s*(\d+)\)", source).groups())
    page_count = len(range(start, stop))
    per_page = int(re.search(r"per_page=(\d+)", source).group(1))
    cap = int(re.search(r"len\(files\) > (\d[\d_]*)", source).group(1).replace("_", ""))
    assert page_count * per_page > cap, (
        "the trailing pagination raise in _load_changed_files is no longer "
        "provably unreachable; remove its '# pragma: no cover' and add a "
        "test that actually covers it"
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "not an object"),
        ({"type": "symlink", "encoding": "base64", "size": 0, "content": ""}, "not a regular"),
        ({"type": "file", "encoding": "base64", "size": -1, "content": ""}, "malformed size"),
        ({"type": "file", "encoding": "base64", "size": policy.MAX_FILE_BYTES + 1, "content": ""}, "size contract"),
        # GitHub's real response shape for a file whose blob exceeds the
        # inline-content ceiling: no content at all, encoding "none".
        ({"type": "file", "encoding": "none", "size": policy.MAX_FILE_BYTES + 1}, "size contract"),
        ({"type": "file", "encoding": "none", "size": 1}, "no inline content"),
        ({"type": "file", "encoding": "none", "size": "not-an-int"}, "no inline content"),
        ({"type": "file", "encoding": "utf-8", "size": 1, "content": "x"}, "not a regular base64 file"),
        ({"type": "file", "encoding": "base64", "size": 1, "content": "!"}, "invalid base64"),
        ({"type": "file", "encoding": "base64", "size": 2, "content": base64.b64encode(b"x").decode()}, "size mismatch"),
        ({"type": "file", "encoding": "base64", "size": 1, "content": base64.b64encode(b"\xff").decode()}, "not valid UTF-8"),
    ],
)
def test_file_content_evidence_is_fail_closed(payload: object, message: str) -> None:
    """Unbounded, nonregular, corrupt, or binary runtime content is rejected."""

    with pytest.raises(policy.PolicyError, match=message):
        policy._load_file_content("api", "a/b", "x y", "a" * 40, "x", lambda url, _token: payload)


def test_file_content_loader_quotes_paths() -> None:
    """Contents API paths are percent-encoded without losing path separators."""

    seen: list[str] = []

    def opener(url: str, _token: str) -> object:
        seen.append(url)
        return encoded_file("ok")

    assert policy._load_file_content("api", "a/b", "dir/a b.conf", "a" * 40, "x", opener) == "ok"
    assert "dir/a%20b.conf" in seen[0]


def test_file_content_loader_accepts_wrapped_base64_content() -> None:
    """GitHub's line-wrapped Contents API base64 remains valid evidence."""

    payload = encoded_file("FROM scratch\n")
    encoded = str(payload["content"])
    payload["content"] = "\n".join(encoded[index : index + 4] for index in range(0, len(encoded), 4))

    assert policy._load_file_content(
        "api", "a/b", "Dockerfile", "a" * 40, "x", lambda _url, _token: payload
    ) == "FROM scratch\n"


class FakeResponse:
    """Context-managed bounded response for direct opener tests."""

    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


def test_github_open_json_accepts_valid_bounded_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default opener parses bounded GitHub JSON."""

    monkeypatch.setattr(policy.github_opener, "open", lambda _request, timeout: FakeResponse(b'{"ok": true}'))
    assert policy._github_open_json("https://api.github.com/repos/a/b", "token") == {"ok": True}


@pytest.mark.parametrize("exc", [URLError("dns"), TimeoutError(), HTTPError("x", 500, "bad", {}, BytesIO())])
def test_github_open_json_sanitizes_transport_failures(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Network failures preserve only their stable class, never response text."""

    def fail(_request: object, timeout: int) -> object:
        assert timeout == 30
        raise exc

    monkeypatch.setattr(policy.github_opener, "open", fail)
    with pytest.raises(policy.PolicyError, match=type(exc).__name__):
        policy._github_open_json("https://api.github.com/repos/a/b", "token")


def test_github_open_json_rejects_oversized_and_malformed_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST evidence must remain one bounded valid JSON document."""

    monkeypatch.setattr(policy.github_opener, "open", lambda _request, timeout: FakeResponse(b"x" * (policy.MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(policy.PolicyError, match="bounded response size"):
        policy._github_open_json("https://api.github.com/repos/a/b", "token")
    monkeypatch.setattr(policy.github_opener, "open", lambda _request, timeout: FakeResponse(b"not-json"))
    with pytest.raises(policy.PolicyError, match="malformed JSON"):
        policy._github_open_json("https://api.github.com/repos/a/b", "token")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/a/b",
        "https://evil.example/repos/a/b",
        "https://user@api.github.com/repos/a/b",
        "https://api.github.com:443/repos/a/b",
        "https://api.github.com/user",
        "https://api.github.com/repos/a/b#fragment",
    ],
)
def test_github_open_json_rejects_nonapproved_origins(url: str) -> None:
    """Evidence collection cannot be redirected to attacker-controlled origins."""

    with pytest.raises(policy.PolicyError, match="approved origin"):
        policy._github_open_json(url, "token")


def test_github_opener_never_constructs_redirect_requests() -> None:
    """The policy opener refuses redirects rather than changing API origins."""

    with pytest.raises(HTTPError) as caught:
        policy.NoRedirectHandler().redirect_request(policy.Request("https://example.com"), None, 302, "Found", {}, "https://evil.example")
    caught.value.close()


def test_annotation_escapes_workflow_command_fields() -> None:
    """Workflow annotations cannot be broken by path or excerpt control syntax."""

    annotation = policy._annotation(policy.Violation("a,b%\n", "rule", 2, "bad%\ntext"))
    assert annotation.startswith("::error file=a%2Cb%25%0A,line=2::")
    assert "bad%25%0Atext" in annotation


def test_main_returns_pass_reject_and_evidence_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI exposes distinct success, policy rejection, and evidence-error statuses."""

    base_args = ["--repository", "a/b", "--pull-request", "1", "--head-sha", "a" * 40, "--event-action", "opened"]
    monkeypatch.setattr(policy, "evaluate_pull_request", lambda **_kwargs: ())
    assert policy.main(base_args, {"GITHUB_TOKEN": "x"}) == 0
    assert "passed" in capsys.readouterr().out

    violation = policy.Violation("Dockerfile", "nginx_container_image", 1, "FROM nginx")
    monkeypatch.setattr(policy, "evaluate_pull_request", lambda **_kwargs: (violation,))
    assert policy.main(base_args, {"GITHUB_TOKEN": "x"}) == 1
    assert "rejected 1" in capsys.readouterr().out

    def evidence_error(**_kwargs: object) -> tuple[object, ...]:
        raise policy.PolicyError("unavailable")

    monkeypatch.setattr(policy, "evaluate_pull_request", evidence_error)
    assert policy.main(base_args, {"GITHUB_TOKEN": "x"}) == 2
    assert "complete evidence" in capsys.readouterr().out


def test_build_parser_uses_pinned_public_api_origin() -> None:
    """The CLI defaults to the approved public GitHub API origin."""

    parser = policy.build_parser()
    args = parser.parse_args([
        "--repository", "a/b", "--pull-request", "1", "--head-sha", "a" * 40, "--event-action", "opened"
    ])
    assert args.api_url == "https://api.github.com"
