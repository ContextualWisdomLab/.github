from scripts.ci import adversarial_evidence as evidence


def test_rejects_circular_adversarial_evidence():
    assert "independent proof" in evidence.adversarial_evidence_rejection_reason(
        "The concurrency group properly handles all cases.",
        ".github/workflows/review.yml",
    )


def test_accepts_independent_proof_anchor_or_exact_path():
    assert (
        evidence.adversarial_evidence_rejection_reason(
            "Focused test test_review_race passed with exit code 0.",
            ".github/workflows/review.yml",
        )
        is None
    )
    assert (
        evidence.adversarial_evidence_rejection_reason(
            ".github/workflows/review.yml:42 rejects the stale head.",
            ".github/workflows/review.yml",
        )
        is None
    )


def test_rejects_unanchored_adversarial_evidence():
    assert "must cite" in evidence.adversarial_evidence_rejection_reason(
        "The implementation has increasing delays.",
        ".github/workflows/review.yml",
    )


def test_rejects_proof_labels_without_an_observed_result():
    assert "observed proof result" in evidence.adversarial_evidence_rejection_reason(
        "Source inspection and test coverage verify error branches are handled.",
        ".github/workflows/review.yml",
    )


def test_accepts_source_or_test_evidence_with_an_observed_result():
    assert (
        evidence.adversarial_evidence_rejection_reason(
            "Source trace at .github/workflows/review.yml:42 rejected the stale head.",
            ".github/workflows/review.yml",
        )
        is None
    )
    assert (
        evidence.adversarial_evidence_rejection_reason(
            "Focused pytest test_review_race passed with exit code 0.",
            ".github/workflows/review.yml",
        )
        is None
    )
    assert (
        evidence.adversarial_evidence_rejection_reason(
            "Test test_review_race confirms the stale head is rejected.",
            ".github/workflows/review.yml",
        )
        is None
    )
