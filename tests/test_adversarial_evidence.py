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
