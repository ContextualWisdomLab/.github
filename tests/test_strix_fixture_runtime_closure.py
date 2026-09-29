"""Regression contract for isolated Strix fixture runtime dependencies."""

from pathlib import Path


SELF_TEST_PATH = Path("scripts/ci/test_strix_quick_gate.sh")
MODEL_UTILS_COPY = 'cp "$REPO_ROOT/scripts/ci/strix_model_utils.sh"'
EVIDENCE_BINDER_COPY = 'cp "$REPO_ROOT/scripts/ci/strix_evidence_binding.py"'


def test_every_isolated_strix_fixture_copies_the_evidence_binder() -> None:
    """Each of the 25 gate fixtures must carry every production runtime helper."""

    self_test = SELF_TEST_PATH.read_text(encoding="utf-8")

    assert self_test.count(MODEL_UTILS_COPY) == 25
    assert self_test.count(EVIDENCE_BINDER_COPY) == 25
