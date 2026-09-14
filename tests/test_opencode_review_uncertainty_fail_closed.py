from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CI_PROMPT = REPO_ROOT / "ci-review-prompt.md"
RUNTIME_PROMPT = REPO_ROOT / "scripts" / "ci" / "opencode_review_prompt_template.md"
GATE = REPO_ROOT / "scripts" / "ci" / "opencode_review_approve_gate.sh"
MARKER = "opencode-review-needs-info"


@pytest.mark.parametrize("prompt_path", [CI_PROMPT, RUNTIME_PROMPT])
def test_gated_prompts_define_fail_closed_uncertainty_without_fabricated_verdict(prompt_path: Path) -> None:
    text = prompt_path.read_text(encoding="utf-8")
    assert MARKER in text
    assert "NO_CONCLUSION" in text
    assert "do not emit" in text.casefold()
    assert "opencode-review-control-v1" in text
    assert "REQUEST_CHANGES" in text
    assert "confirmed" in text.casefold()


def test_insufficient_evidence_marker_fails_closed_without_control_block(tmp_path: Path) -> None:
    review_body = tmp_path / "review.md"
    review_body.write_text(
        "\n".join(
            [
                "<!-- opencode-review-gate head_sha=head run_id=run run_attempt=attempt -->",
                "<!-- opencode-review-needs-info head_sha=head run_id=run run_attempt=attempt -->",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["bash", str(GATE), "head", "run", "attempt", str(review_body)],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 4
    assert completed.stdout.strip() == "NO_CONCLUSION"
    assert "opencode-review-control-v1" not in review_body.read_text(encoding="utf-8")
