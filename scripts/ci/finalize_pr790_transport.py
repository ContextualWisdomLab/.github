#!/usr/bin/env python3
"""Apply the exact reviewed transient-transport repair for pull request 790."""

from __future__ import annotations

from pathlib import Path


PRODUCTION_PATH = Path("scripts/ci/materialize_base_python_requirements.py")
DOCTORING_PATH = Path("docs/doctoring/trusted-uv-transient-download-retry.md")
CHANGELOG_PATH = Path("CHANGELOG.md")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment or fail before an ambiguous edit."""
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def repair_production() -> None:
    """Restrict retries to an explicit transient HTTP and transport set."""
    source = PRODUCTION_PATH.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "import argparse\nimport atexit\n",
        "import argparse\nimport atexit\nimport errno\n",
        "errno import",
    )
    source = replace_once(
        source,
        "import shutil\nimport subprocess\nimport sys\n",
        "import shutil\nimport socket\nimport ssl\nimport subprocess\nimport sys\n",
        "transport imports",
    )
    source = replace_once(
        source,
        "    {408, 429, 500, 502, 503, 504}\n",
        "    {408, 425, 429, 500, 502, 503, 504}\n",
        "retryable HTTP set",
    )
    constant_anchor = "TRUSTED_UV_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024\n"
    constant_block = """TRUSTED_UV_TRANSIENT_ERRNO = frozenset(
    {
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }
)
"""
    source = replace_once(
        source,
        constant_anchor,
        constant_block + constant_anchor,
        "transient errno set",
    )
    download_anchor = '''def _download_trusted_uv_archive() -> bytes:
    """Download the fixed archive with bounded transient transport retries."""
'''
    helpers = '''def _transport_failure_root(error: BaseException) -> BaseException:
    """Return the bounded diagnostic root for one transport exception."""
    if (
        isinstance(error, urllib.error.URLError)
        and isinstance(error.reason, BaseException)
    ):
        return error.reason
    return error


def _transient_transport_failure_label(
    error: BaseException,
) -> str | None:
    """Return bounded evidence only for provably transient transport failures."""
    root = _transport_failure_root(error)
    if isinstance(root, (ssl.SSLCertVerificationError, ssl.SSLError)):
        return None
    if isinstance(root, socket.gaierror):
        return "temporary DNS" if root.errno == socket.EAI_AGAIN else None
    if isinstance(root, TimeoutError):
        return "timeout"
    if isinstance(root, OSError) and root.errno in TRUSTED_UV_TRANSIENT_ERRNO:
        return f"transport errno {root.errno}"
    return None


'''
    source = replace_once(
        source,
        download_anchor,
        helpers + download_anchor,
        "transport helpers",
    )
    old_handler = '''        except (urllib.error.URLError, OSError) as exc:
            failure_label = type(exc).__name__
            failure = exc
'''
    new_handler = '''        except (urllib.error.URLError, OSError) as exc:
            failure_label = _transient_transport_failure_label(exc)
            if failure_label is None:
                root = _transport_failure_root(exc)
                raise RuntimeError(
                    "trusted uv archive download failed: "
                    f"{type(root).__name__}"
                ) from exc
            failure = exc
'''
    source = replace_once(
        source,
        old_handler,
        new_handler,
        "transport exception classifier",
    )
    PRODUCTION_PATH.write_text(source, encoding="utf-8")


def update_evidence() -> None:
    """Record the exact fail-closed retry boundary in permanent evidence."""
    doctoring = DOCTORING_PATH.read_text(encoding="utf-8")
    heading = "## Closed retry classification"
    if heading not in doctoring:
        doctoring = doctoring.rstrip() + """

## Closed retry classification

The retryable HTTP set is exactly `408`, `425`, `429`, `500`, `502`, `503`, and
`504`. Transport retries are limited to temporary DNS (`EAI_AGAIN`), timeout,
connection reset/refused/aborted, and explicit host or network unavailable
errors. Certificate verification, other TLS failures, permanent DNS, malformed
`URLError.reason`, local permission errors, and every unclassified `OSError`
fail after one attempt.

Each attempt repeats the same literal Astral URL and exact timeout. A failed
response body is scoped to that attempt, so partial bytes are discarded before
retry. Diagnostics expose only a bounded HTTP status, transport errno, or
exception class and never exception text, URL-derived credentials, headers, or
body content.
"""
        DOCTORING_PATH.write_text(doctoring, encoding="utf-8")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    entry = (
        "- Restrict trusted uv retries to HTTP 408/425/429/500/502/503/504 "
        "and explicitly classified temporary DNS, timeout, connection, host, "
        "or network failures; TLS, permanent DNS, malformed, and unclassified "
        "local errors now fail after one attempt.\n"
    )
    if entry not in changelog:
        changelog = replace_once(
            changelog,
            "### Fixed\n\n",
            "### Fixed\n\n" + entry,
            "CHANGELOG Fixed section",
        )
        CHANGELOG_PATH.write_text(changelog, encoding="utf-8")


def main() -> int:
    """Apply the reviewed production change and permanent evidence."""
    repair_production()
    update_evidence()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
