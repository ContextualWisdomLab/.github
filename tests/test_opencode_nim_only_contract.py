"""Focused contracts for the OpenCode provider-boundary migration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    """Return UTF-8 repository text for a policy assertion."""
    return (ROOT / path).read_text(encoding="utf-8")


def test_checked_in_opencode_config_enables_only_nvidia_nim():
    """The checked-in default cannot silently route review data to GitHub Models."""
    config = read_repo_file("opencode.jsonc")

    assert '"enabled_providers": ["nvidia-nim"]' in config
    assert '"model": "nvidia-nim/' in config
    assert '"small_model": "nvidia-nim/' in config
    assert "github-models" not in config
    assert "models.github.ai" not in config
    assert "STRIX_GITHUB_MODELS_TOKEN" not in config


def test_review_dispatch_uses_scoped_nim_and_has_no_github_models_candidate():
    """Hosted review candidates keep the scoped NIM credential boundary."""
    workflow = read_repo_file(".github/workflows/opencode-review-dispatch.yml")
    candidate_line = next(
        line for line in workflow.splitlines() if "OPENCODE_MODEL_CANDIDATES:" in line
    )

    assert "nvidia-nim/" in candidate_line
    assert "github-models/" not in candidate_line
    assert "opencode/gpt-5.6-terra" not in candidate_line
    assert "NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "failing closed without GitHub Models fallback" in read_repo_file(
        "scripts/ci/run_opencode_review_model_pool.sh"
    )
