"""Documentation contracts for the closed trusted uv retry boundary."""

from pathlib import Path


def test_trusted_uv_retry_documentation_matches_closed_policy() -> None:
    """Operator docs must not broaden the exact production retry classifier."""
    repository_root = Path(__file__).resolve().parents[1]
    doctoring = (
        repository_root / "docs/doctoring/trusted-uv-transient-download-retry.md"
    ).read_text(encoding="utf-8")
    changelog = (repository_root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "HTTP 408, 425, 429, 500, 502, 503, and 504" in doctoring
    assert "temporary DNS (`EAI_AGAIN`)" in doctoring
    assert "connection-level `urllib.error.URLError` or `OSError` failures" not in doctoring
    assert "408, 429, or 5xx" not in changelog
