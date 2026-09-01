"""Executable traceability contract for the Noema observed-probe doctoring."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs/doctoring/noema-observed-defect-probe-taxonomy.md"
WORKFLOW = ROOT / ".github/workflows/noema-observed-probe-quality-ci.yml"


def _pull_request_paths(text: str) -> set[str]:
    """Return exact pull_request path filters from the focused workflow."""
    paths: set[str] = set()
    in_paths = False
    for line in text.splitlines():
        if line == "    paths:":
            in_paths = True
            continue
        if in_paths and line.startswith("      - "):
            paths.add(line.removeprefix("      - ").strip())
            continue
        if in_paths and line.strip() and not line.startswith("      "):
            break
    return paths


def test_observed_probe_doctoring_records_closed_taxonomy_and_claim_boundary() -> None:
    """Doctoring must retain every probe class and the no-superiority claim boundary."""
    text = DOCTORING.read_text(encoding="utf-8")
    for probe_kind in (
        "mutable_alias",
        "time_of_check_time_of_use",
        "execution_identity",
        "coercion_boundary",
        "test_oracle",
        "cross_contract",
        "authority_boundary",
        "dependency_context",
        "state_machine_race",
    ):
        assert f"`{probe_kind}`" in text
    assert "does not claim parity or superiority" in text
    assert "ContextualWisdomLab/noema#528" in text
    assert "33500648307" in text


def test_focused_workflow_triggers_for_every_installed_requirement_file() -> None:
    """A lockfile that defines the focused environment must trigger that focused gate."""
    text = WORKFLOW.read_text(encoding="utf-8")
    installed_requirements = set(re.findall(r"(?:^|\s)-r\s+([A-Za-z0-9_./-]+)", text))
    assert installed_requirements
    assert installed_requirements <= _pull_request_paths(text)
