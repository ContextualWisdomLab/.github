"""Documentation contracts for the closed trusted uv retry boundary."""

from pathlib import Path


def test_trusted_uv_retry_documentation_matches_closed_policy() -> None:
    """Operator docs must not broaden or narrow the production retry classifier."""
    repository_root = Path(__file__).resolve().parents[1]
    doctoring = (
        repository_root / "docs/doctoring/trusted-uv-transient-download-retry.md"
    ).read_text(encoding="utf-8")
    changelog = (repository_root / "CHANGELOG.md").read_text(encoding="utf-8")
    agents = (repository_root / "AGENTS.md").read_text(encoding="utf-8")
    architecture = (repository_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
    normalized_doctoring = doctoring.replace("`", "")

    assert "HTTP 408, 425, 429, 500, 502, 503, 504, and 522" in normalized_doctoring
    assert "temporary DNS resolution reported as EAI_AGAIN" in normalized_doctoring
    assert "connection-level urllib.error.URLError or OSError failures" not in normalized_doctoring
    assert "HTTP 408, 425, 429, 500, 502, 503, 504, and 522" in agents
    assert "408 / 425 / 429 / 500 / 502 / 503 / 504 / 522" in architecture
    assert "408, 429, or 5xx" not in changelog
