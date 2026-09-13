"""Static security and architecture contracts for the explicit source-repair workflow."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-source-repair.yml"


def _job_names(text: str) -> set[str]:
    """Return top-level job keys without requiring a YAML runtime dependency."""
    jobs_text = text.split("\njobs:\n", 1)[1]
    return set(re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs_text, flags=re.MULTILINE))


def _job_block(text: str, job_name: str) -> str:
    """Return one top-level job block from the workflow source text."""
    jobs_text = text.split("\njobs:\n", 1)[1]
    marker = f"  {job_name}:\n"
    block = jobs_text.split(marker, 1)[1]
    next_job = re.search(r"^  [A-Za-z0-9_-]+:\s*$", block, flags=re.MULTILINE)
    return block[: next_job.start()] if next_job else block


def test_source_repair_worker_uses_only_contextual_orchestrator_free() -> None:
    """The model-backed mutation lane must not select a provider/model or paid fallback."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "contextual-orchestrator/orchestrator/free" in text
    assert "nvidia-nim/" not in text.lower()
    assert "openrouter/" not in text.lower()
    assert "openai/" not in text.lower()
    assert "--force" not in text
    assert "core.hooksPath=/dev/null push" in text


def test_source_repair_has_separate_sweep_and_serial_writer() -> None:
    """Discovery may recur, while one target PR has exactly one mutation writer at a time."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert _job_names(text) == {"sweep-source-repair-comments", "source-repair"}
    source_repair = _job_block(text, "source-repair")
    assert "    concurrency:\n" in source_repair
    assert "      cancel-in-progress: false\n" in source_repair
    assert "target_repository" in source_repair and "pr_number" in source_repair
    assert "    timeout-minutes:" not in source_repair


def test_worker_revalidates_before_normal_push() -> None:
    """Mutation requires a second authority/scope check immediately before publication."""
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text.split("- name: Revalidate authority and push a normal commit", 1)[1]
    assert "agent_source_repair.py" in step
    assert "cmp \"$RUNNER_TEMP/agent-source-repair-allowed-paths.zlist\"" in step
    assert "live_head" in step
    assert "git -c core.hooksPath=/dev/null push" in step
    assert "merge" not in step.lower()


def test_review_mentions_remain_separate_from_source_mutation() -> None:
    """The source writer is a distinct command path and does not weaken review workflows."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [agent-source-repair]" in text
    assert "@opencode-agent" not in text
    assert "agent-mention-opencode" not in text
