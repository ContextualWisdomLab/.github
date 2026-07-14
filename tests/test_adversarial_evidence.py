from scripts.ci import adversarial_evidence as evidence

SOURCE_RECEIPT = f"source-line-sha256={'a' * 64}"


def test_rejects_circular_adversarial_evidence():
    assert "independent proof" in evidence.adversarial_evidence_rejection_reason(
        "The concurrency group properly handles all cases.",
        ".github/workflows/review.yml",
    )


def test_accepts_independent_proof_anchor_and_rejects_path_only():
    assert (
        evidence.adversarial_evidence_rejection_reason(
            f"Focused test for .github/workflows/review.yml passed with exit code 0. {SOURCE_RECEIPT}",
            ".github/workflows/review.yml",
        )
        is None
    )
    assert "must cite" in evidence.adversarial_evidence_rejection_reason(
        f".github/workflows/review.yml passed. {SOURCE_RECEIPT}",
        ".github/workflows/review.yml",
    )


def test_rejects_unanchored_adversarial_evidence():
    assert "must cite" in evidence.adversarial_evidence_rejection_reason(
        "The implementation has increasing delays.",
        ".github/workflows/review.yml",
    )


def test_rejects_proof_labels_without_an_observed_result():
    assert "observed proof result" in evidence.adversarial_evidence_rejection_reason(
        f"Source inspection at .github/workflows/review.yml has test coverage. {SOURCE_RECEIPT}",
        ".github/workflows/review.yml",
    )


def test_accepts_source_or_test_evidence_with_an_observed_result():
    assert (
        evidence.adversarial_evidence_rejection_reason(
            f"Source trace at .github/workflows/review.yml:42 rejected the stale head. {SOURCE_RECEIPT}",
            ".github/workflows/review.yml",
        )
        is None
    )
    assert (
        evidence.adversarial_evidence_rejection_reason(
            f"Focused pytest for .github/workflows/review.yml passed with exit code 0. {SOURCE_RECEIPT}",
            ".github/workflows/review.yml",
        )
        is None
    )
    assert (
        evidence.adversarial_evidence_rejection_reason(
            f"Test for .github/workflows/review.yml confirms the stale head is rejected. {SOURCE_RECEIPT}",
            ".github/workflows/review.yml",
        )
        is None
    )


def test_requires_the_exact_probe_path_and_line_when_line_is_supplied():
    """Unrelated and nonexistent-looking citations cannot authorize a probe."""
    reason = evidence.adversarial_evidence_rejection_reason(
        f"Source trace at unrelated.py:999 confirmed the branch. {SOURCE_RECEIPT}",
        ".github/workflows/review.yml",
        42,
    )

    assert reason == "must cite the exact probe path and positive line"
    assert (
        evidence.adversarial_evidence_rejection_reason(
            f"Source trace at .github/workflows/review.yml:42 rejected the stale head. {SOURCE_RECEIPT}",
            ".github/workflows/review.yml",
            42,
        )
        is None
    )
    assert "exact probe path" in evidence.adversarial_evidence_rejection_reason(
        f"Source trace at prefix.github/workflows/review.yml:42 rejected the stale head. {SOURCE_RECEIPT}",
        ".github/workflows/review.yml",
        42,
    )


def test_path_only_citation_rejects_longer_path_substrings():
    """A filename embedded inside another path is not an exact citation."""
    assert "exact probe path" in evidence.adversarial_evidence_rejection_reason(
        f"Focused test for prefix.github/workflows/review.yml passed. {SOURCE_RECEIPT}",
        ".github/workflows/review.yml",
    )


def test_requires_exactly_one_source_line_receipt():
    """Free-form proof prose cannot pass without a bound current-head receipt."""
    message = "Source trace at .github/workflows/review.yml:42 rejected the stale head."
    assert (
        "exactly one source-line-sha256"
        in evidence.adversarial_evidence_rejection_reason(
            message,
            ".github/workflows/review.yml",
            42,
        )
    )
    assert (
        "exactly one source-line-sha256"
        in evidence.adversarial_evidence_rejection_reason(
            f"{message} {SOURCE_RECEIPT} {SOURCE_RECEIPT}",
            ".github/workflows/review.yml",
            42,
        )
    )
