#!/usr/bin/env python3
"""Prove installed Strix root/child/grandchild prompts without a model or sandbox."""

from __future__ import annotations

import asyncio
import json
import hashlib
from pathlib import Path
import runpy
import tempfile


def main() -> None:
    """Run the trusted launcher registration and actual graph-tool/factory contract."""
    launcher_path = Path(__file__).resolve().parents[1] / "scripts/ci/strix_review_skill_launcher.py"
    launcher = runpy.run_path(str(launcher_path))
    with launcher["registered_review_skills"]() as instructions:
        from strix.skills import registered_skill_dirs
        from strix.utils.resource_paths import get_strix_resource_path

        registered = registered_skill_dirs()[0]
        for mode in ("quick", "standard", "deep"):
            original = get_strix_resource_path("skills", "scan_modes", mode + ".md").read_bytes()
            extended = (registered / "scan_modes" / (mode + ".md")).read_bytes()
            assert extended == original + b"\n\n" + instructions.encode("utf-8")
            assert hashlib.sha256(extended[:len(original)]).digest() == hashlib.sha256(original).digest()
        asyncio.run(_check_hierarchy(instructions))
    print("CWL_STRIX_REVIEW_SKILLS root/child/grandchild/resumed all_modes all_inheritance PASS")


async def _check_hierarchy(instructions: str) -> None:
    """Replace only model-loop startup; execute the real tool and recursive factory."""
    from agents.tool_context import ToolContext
    from strix.agents.factory import build_strix_agent, make_child_factory
    from strix.core import execution
    from strix.core.agents import AgentCoordinator
    from strix.tools.agents_graph.tools import create_agent

    start_child_runner = execution._start_child_runner
    try:
        with tempfile.TemporaryDirectory(prefix="cwl-strix-skill-probe-") as directory:
            for mode in ("quick", "standard", "deep"):
                for inherit in (True, False):
                    coordinator = AgentCoordinator()
                    await coordinator.register("root", "Root", parent_id=None)
                    factory = make_child_factory(scan_mode=mode)
                    agents = [build_strix_agent(name="root", is_root=True, scan_mode=mode)]
                    histories = []
                    initial_inputs = []

                    async def capture(**kwargs):
                        """Capture constructed agents and inputs without starting a model loop."""
                        agents.append(kwargs["child_agent"])
                        initial_inputs.append(kwargs["initial_input"])

                    execution._start_child_runner = capture

                    async def spawn(**kwargs):
                        """Record inherited context while invoking the real child factory."""
                        histories.append(kwargs["parent_history"])
                        return await execution.spawn_child_agent(
                            coordinator=coordinator, factory=factory,
                            agents_db_path=Path(directory) / "agents.db", sessions_to_close=[],
                            run_config=None, max_turns=1, interactive=False, **kwargs,
                        )

                    parent = "root"
                    for name in ("child", "grandchild"):
                        context = ToolContext(
                            context={"agent_id": parent, "coordinator": coordinator,
                                     "spawn_child_agent": spawn},
                            tool_name="create_agent", tool_call_id=name, tool_arguments="{}",
                            turn_input=[{"role": "user", "content": "parent evidence"}],
                        )
                        result = json.loads(await create_agent.on_invoke_tool(
                            context, json.dumps({"name": name, "task": "test", "skills": [],
                                                 "inherit_context": inherit}),
                        ))
                        assert result["success"], result
                        child_id = result["agent_id"]
                        assert coordinator.parent_of[child_id] == parent
                        parent = child_id
                    assert len(agents) == 3
                    for child_id in coordinator.parent_of:
                        if child_id != "root":
                            await coordinator.set_status(child_id, "running")
                    await execution.respawn_subagents(
                        coordinator=coordinator, factory=factory,
                        agents_db_path=Path(directory) / "agents.db", sessions_to_close=[],
                        run_config=None, max_turns=1, interactive=False,
                        parent_ctx={"agent_id": "root", "spawn_child_agent": spawn}, root_id="root",
                    )
                    assert len(agents) == 5
                    assert initial_inputs[-2:] == [[], []]
                    assert all(instructions in agent.instructions for agent in agents), (mode, inherit)
                    assert all(bool(history) == inherit for history in histories)
    finally:
        execution._start_child_runner = start_child_runner


if __name__ == "__main__":
    main()
