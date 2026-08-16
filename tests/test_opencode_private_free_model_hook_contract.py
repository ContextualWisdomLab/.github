"""The live model-pool runner must source the private free-model hook."""

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "scripts" / "ci" / "run_opencode_review_model_pool.sh"
HOOK = REPO / "scripts" / "ci" / "opencode_private_free_model_hook.sh"
POLICY = REPO / "scripts" / "ci" / "opencode_private_free_model_policy.py"
GUARD = REPO / "scripts" / "ci" / "opencode_provider_guard.sh"


def test_live_runner_sources_private_free_model_hook() -> None:
    """Private free-model opt-in is a hook, not a replacement runner."""

    runner = RUNNER.read_text(encoding="utf-8")
    hook = HOOK.read_text(encoding="utf-8")
    assert "opencode_private_free_model_hook.sh" in runner
    assert "apply_private_free_model_policy" in runner
    assert "maybe_enable_private_free_models" in hook
    assert "install_provider_guard" in hook
    assert POLICY.is_file()
    assert GUARD.is_file()
    assert "run_opencode_review_model_pool_impl.sh" not in runner
