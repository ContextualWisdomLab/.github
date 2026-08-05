#!/usr/bin/env python3
"""Apply the reviewed trusted-uv transient retry patch exactly once."""

from __future__ import annotations

from pathlib import Path


MATERIALIZER = Path("scripts/ci/materialize_base_python_requirements.py")
CHANGELOG = Path("CHANGELOG.md")


REPLACEMENT = '''def _download_trusted_uv_archive() -> bytes:
    """Download the fixed archive with bounded transient transport retries."""
    _install_trusted_uv_url_opener()
    attempt_limit = len(TRUSTED_UV_DOWNLOAD_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(1, attempt_limit + 1):
        try:
            # Keep the audited URL literal at the network sink so static analysis can
            # prove that neither user data nor repository content selects a scheme,
            # host, path, query, fragment, method, or request header.
            with urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected  # nosec B310
                "https://releases.astral.sh/github/uv/releases/download/0.12.1/"
                "uv-x86_64-unknown-linux-gnu.tar.gz",
                timeout=TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
            ) as response:
                final_url = urllib.parse.urlparse(response.geturl())
                try:
                    final_port = final_url.port
                except ValueError as exc:
                    raise RuntimeError(
                        "trusted uv archive redirected outside the fixed "
                        "releases.astral.sh HTTPS origin"
                    ) from exc
                if (
                    (final_url.scheme, final_url.hostname)
                    != ("https", "releases.astral.sh")
                    or final_port not in (None, 443)
                ):
                    raise RuntimeError(
                        "trusted uv archive redirected outside the fixed "
                        "releases.astral.sh HTTPS origin"
                    )
                payload = bytearray()
                while len(payload) <= TRUSTED_UV_DOWNLOAD_MAX_BYTES:
                    chunk = response.read(
                        TRUSTED_UV_DOWNLOAD_MAX_BYTES + 1 - len(payload)
                    )
                    if not chunk:
                        break
                    payload.extend(chunk)

            if len(payload) > TRUSTED_UV_DOWNLOAD_MAX_BYTES:
                raise RuntimeError(
                    "trusted uv archive exceeded the bounded download size"
                )
            return bytes(payload)
        except urllib.error.HTTPError as exc:
            if exc.code not in TRUSTED_UV_RETRYABLE_HTTP_STATUS:
                raise RuntimeError(
                    f"trusted uv archive download failed: HTTP {exc.code}"
                ) from exc
            failure_label = f"HTTP {exc.code}"
            failure: BaseException = exc
        except (urllib.error.URLError, OSError) as exc:
            failure_label = type(exc).__name__
            failure = exc

        if attempt == attempt_limit:
            raise RuntimeError(
                "trusted uv archive download failed: "
                f"{failure_label} after {attempt} attempts"
            ) from failure
        time.sleep(TRUSTED_UV_DOWNLOAD_RETRY_DELAYS_SECONDS[attempt - 1])

    raise AssertionError("trusted uv retry loop must return or raise")  # pragma: no cover
'''


def apply_materializer_patch() -> None:
    """Patch imports, constants, and the downloader with exact anchor checks."""

    text = MATERIALIZER.read_text(encoding="utf-8")
    import_anchor = "import tempfile\nimport urllib.parse\nimport urllib.request\n"
    import_replacement = (
        "import tempfile\nimport time\nimport urllib.error\n"
        "import urllib.parse\nimport urllib.request\n"
    )
    if text.count(import_anchor) != 1:
        raise RuntimeError("trusted uv import anchor drifted")
    text = text.replace(import_anchor, import_replacement, 1)

    timeout_anchor = "TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS = 120\n"
    constants = (
        "TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS = 120\n"
        "TRUSTED_UV_DOWNLOAD_RETRY_DELAYS_SECONDS = (1.0, 2.0)\n"
        "TRUSTED_UV_RETRYABLE_HTTP_STATUS = frozenset(\n"
        "    {408, 429, 500, 502, 503, 504}\n"
        ")\n"
    )
    if text.count(timeout_anchor) != 1:
        raise RuntimeError("trusted uv timeout anchor drifted")
    text = text.replace(timeout_anchor, constants, 1)

    start = text.index("def _download_trusted_uv_archive() -> bytes:\n")
    end = text.index("\n\ndef _verified_uv_binary", start)
    MATERIALIZER.write_text(text[:start] + REPLACEMENT + text[end:], encoding="utf-8")


def apply_changelog_patch() -> None:
    """Record the retry boundary in the canonical Unreleased Fixed section."""

    text = CHANGELOG.read_text(encoding="utf-8")
    anchor = "### Fixed\n\n"
    bullet = (
        "- Retried the fixed, checksum-pinned trusted uv archive download at most "
        "twice after transient transport, 408, 429, or 5xx availability failures "
        "while keeping redirects, permanent 4xx responses, origin drift, size, "
        "checksum, archive, and version failures immediately fail-closed.\n"
    )
    if text.count(anchor) != 1:
        raise RuntimeError("CHANGELOG Fixed anchor drifted")
    if bullet not in text:
        CHANGELOG.write_text(text.replace(anchor, anchor + bullet, 1), encoding="utf-8")


def main() -> int:
    """Apply both exact patches and return a process success status."""

    apply_materializer_patch()
    apply_changelog_patch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
