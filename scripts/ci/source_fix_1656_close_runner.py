"""One-shot repair driver for PR 1656 close-event runner pressure."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github/workflows"
NATIVE_WORKFLOWS = (
    "close-empty-pr.yml",
    "codeql-pr.yml",
    "osv-scanner-pr.yml",
    "pr-review-merge-scheduler.yml",
    "python-security.yml",
    "sast-semgrep.yml",
    "sbom-generation.yml",
    "scorecard-pr.yml",
    "secret-scan.yml",
    "security-scan.yml",
)


def remove_noop_close_job(text: str, filename: str) -> str:
    """Remove only the runner-backed close sentinel job from a workflow."""
    lines = text.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\n") == "  cancel-closed-pr-runs:"
    ]
    if len(starts) > 1:
        raise RuntimeError(f"{filename}: multiple close sentinel jobs found")
    if starts:
        start = starts[0]
        end = len(lines)
        job_key = re.compile(r"^  [A-Za-z0-9_.-]+:\s*$")
        for index in range(start + 1, len(lines)):
            if job_key.match(lines[index].rstrip("\n")):
                end = index
                break
        del lines[start:end]
    updated = "".join(lines)
    updated = re.sub(
        r"\n  # Compatibility sentinel[^\n]*\n(?:  #[^\n]*\n){0,3}",
        "\n",
        updated,
    )
    return updated


def repair_workflows() -> None:
    """Remove needless close-event runner admission from native concurrency workflows."""
    for filename in NATIVE_WORKFLOWS:
        path = WORKFLOW_DIR / filename
        updated = remove_noop_close_job(path.read_text(encoding="utf-8"), filename)
        if "cancel-closed-pr-runs:" in updated:
            raise RuntimeError(f"{filename}: no-op close job remains")
        if "closed" not in updated:
            raise RuntimeError(f"{filename}: closed trigger missing")
        concurrency = updated.split("concurrency:", 1)[1].split("permissions:", 1)[0]
        if "github.event.pull_request.number" not in concurrency:
            raise RuntimeError(f"{filename}: PR-stable concurrency missing")
        if "github.event.pull_request.head.sha" in concurrency:
            raise RuntimeError(f"{filename}: head SHA fragments concurrency")
        if "cancel-in-progress:" not in concurrency:
            raise RuntimeError(f"{filename}: cancellation policy missing")
        if "github.event.action != 'closed'" not in updated:
            raise RuntimeError(f"{filename}: expensive/evidence job lacks close guard")
        path.write_text(updated, encoding="utf-8")


def repair_consolidated_contract() -> None:
    """Replace the stale generic close-job assertion with the native policy."""
    path = ROOT / "tests/test_required_workflow_queue_contract.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        == "test_pull_request_close_events_cancel_superseded_runs_without_heavy_jobs"
    )
    start = function.lineno - 1
    end = function.end_lineno
    lines = text.splitlines(keepends=True)
    replacement = '''def test_pull_request_close_events_cancel_superseded_runs_without_heavy_jobs() -> None:\n    """Close events retire old runs without needless runner admission."""\n    native_concurrency_workflows = (\n        "close-empty-pr.yml",\n        "codeql-pr.yml",\n        "osv-scanner-pr.yml",\n        "pr-review-merge-scheduler.yml",\n        "python-security.yml",\n        "sast-semgrep.yml",\n        "sbom-generation.yml",\n        "scorecard-pr.yml",\n        "secret-scan.yml",\n        "security-scan.yml",\n    )\n\n    for filename in native_concurrency_workflows:\n        workflow = workflow_text(filename)\n        assert "closed" in workflow\n        assert "cancel-closed-pr-runs:" not in workflow\n        concurrency_contract = workflow.split("concurrency:", 1)[1].split(\n            "permissions:", 1\n        )[0]\n        assert "github.event.pull_request.number" in concurrency_contract\n        assert "github.event.pull_request.head.sha" not in concurrency_contract\n        assert "cancel-in-progress:" in concurrency_contract\n        assert "github.event.action != 'closed'" in workflow\n\n    noema = workflow_text("noema-review.yml")\n    assert "closed" in noema\n    assert "cancel-closed-pr-runs:" in noema\n    assert "Cancel queued and running Noema reviews for the closed pull request" in noema\n    noema_cleanup = noema.split("  cancel-closed-pr-runs:", 1)[1].split(\n        "  noema-review:", 1\n    )[0]\n    assert "actions: write" in noema_cleanup\n    assert "actions/checkout" not in noema_cleanup\n    assert "cleanup skipped" not in noema_cleanup\n    assert "github.event.action != 'closed'" in noema\n\n    strix_workflow = workflow_text("strix.yml")\n    assert "closed" in strix_workflow\n    assert "cancel-superseded-pr-runs:" in strix_workflow\n    assert (\n        "Cancel queued and running scans for superseded or closed pull request heads"\n        in strix_workflow\n    )\n    assert "TARGET_PR_HEAD_SHA" in strix_workflow\n    assert 'select(.event == "pull_request_target")' in strix_workflow\n    assert 'select(.event == "repository_dispatch")' not in strix_workflow\n    assert "(.pull_requests // [])" in strix_workflow\n    assert ".head.sha // \\\"\\\"" in strix_workflow\n    assert "leaving runs unchanged" in strix_workflow\n    assert (\n        "for active_status in queued in_progress requested waiting pending"\n        in strix_workflow\n    )\n    assert "github.event.action != 'closed'" in strix_workflow\n    assert "cancel-in-progress: false" in strix_workflow\n    assert "Keep provider-backed scans serial per repository" in strix_workflow\n\n    opencode_bootstrap = workflow_text("opencode-review.yml")\n    assert (\n        "types: [opened, synchronize, reopened, ready_for_review, converted_to_draft, closed]"\n        in opencode_bootstrap\n    )\n    assert "actions/checkout" not in opencode_bootstrap\n    assert "$" + "{{ secrets." not in opencode_bootstrap\n'''
    updated = "".join(lines[:start]) + replacement + "".join(lines[end:])
    ast.parse(updated)
    path.write_text(updated, encoding="utf-8")


def repair_focused_regression() -> None:
    """Expand the focused regression over every native-concurrency workflow."""
    path = ROOT / "tests/test_close_empty_pr_queue_pressure.py"
    cases = (
        ("close-empty-pr.yml", "  close-empty:"),
        ("codeql-pr.yml", "  detect-languages:"),
        ("osv-scanner-pr.yml", "  osv-scan:"),
        ("pr-review-merge-scheduler.yml", "  scan-pr-queue:"),
        ("python-security.yml", "  detect-python:"),
        ("sast-semgrep.yml", "  semgrep:"),
        ("sbom-generation.yml", "  generate-sbom:"),
        ("scorecard-pr.yml", "  analysis:"),
        ("secret-scan.yml", "  gitleaks:"),
        ("security-scan.yml", "  osv-scan:"),
    )
    rows = "\n".join(f"        ({name!r}, {job!r})," for name, job in cases)
    content = f'''"""Regression contracts for close-event runner admission pressure."""\n\nfrom pathlib import Path\n\nimport pytest\n\nWORKFLOWS = Path(__file__).parents[1] / ".github/workflows"\n\n\n@pytest.mark.parametrize(\n    ("filename", "evidence_job"),\n    (\n{rows}\n    ),\n)\ndef test_closed_pull_request_does_not_allocate_a_noop_runner(\n    filename: str, evidence_job: str\n) -> None:\n    """PR-stable concurrency retires close work without a no-op runner."""\n    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")\n    concurrency = workflow.split("concurrency:", 1)[1].split("permissions:", 1)[0]\n    assert "closed" in workflow\n    assert "github.event.pull_request.number" in concurrency\n    assert "github.event.pull_request.head.sha" not in concurrency\n    assert "cancel-in-progress:" in concurrency\n    assert "cancel-closed-pr-runs:" not in workflow\n    assert "github.event.action != 'closed'" in workflow\n    assert evidence_job in workflow\n'''
    ast.parse(content)
    path.write_text(content, encoding="utf-8")


def verify() -> None:
    """Verify native cleanup and preserve trusted explicit Noema/Strix cleanup."""
    for filename in NATIVE_WORKFLOWS:
        workflow = (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
        concurrency = workflow.split("concurrency:", 1)[1].split("permissions:", 1)[0]
        assert "closed" in workflow
        assert "github.event.pull_request.number" in concurrency
        assert "github.event.pull_request.head.sha" not in concurrency
        assert "cancel-in-progress:" in concurrency
        assert "cancel-closed-pr-runs:" not in workflow
        assert "github.event.action != 'closed'" in workflow
    noema = (WORKFLOW_DIR / "noema-review.yml").read_text(encoding="utf-8")
    strix = (WORKFLOW_DIR / "strix.yml").read_text(encoding="utf-8")
    assert "Cancel queued and running Noema reviews for the closed pull request" in noema
    assert "Cancel queued and running scans for superseded or closed pull request heads" in strix
    ast.parse((ROOT / "tests/test_required_workflow_queue_contract.py").read_text(encoding="utf-8"))
    ast.parse((ROOT / "tests/test_close_empty_pr_queue_pressure.py").read_text(encoding="utf-8"))


def main() -> None:
    """Apply and verify the one-shot source repair."""
    repair_workflows()
    repair_consolidated_contract()
    repair_focused_regression()
    verify()
    print(f"validated {len(NATIVE_WORKFLOWS)} native-concurrency close-event workflows")


if __name__ == "__main__":
    main()
