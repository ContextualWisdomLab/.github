#!/usr/bin/env python3
"""Run the installed Strix CLI with verified methods in every scan-mode prompt."""

from __future__ import annotations

from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
import re
import runpy
import tempfile


def review_skill_instructions() -> str:
    """Read the central bundle without importing modules from the scan target."""
    source = Path(__file__).resolve().with_name("review_skill_bundle.py")
    return runpy.run_path(str(source))["review_skill_instructions"]()


@contextmanager
def registered_review_skills():
    """Keep immutable, verified scan-mode extensions alive for the entire CLI run."""
    from strix.agents.prompt import render_system_prompt
    from strix.skills import load_skills, register_skill_dir, registered_skill_dirs
    from strix.utils.resource_paths import get_strix_resource_path

    root = Path(__file__).resolve().parents[2]
    requirement = re.search(
        r"^strix-agent==([^\s]+)$",
        (root / "requirements-strix-ci.txt").read_text(), re.MULTILINE,
    )
    if requirement is None or version("strix-agent") != requirement[1]:
        raise ValueError("Installed Strix does not match the trusted version pin")
    if registered_skill_dirs():
        raise ValueError("Strix skill registration must start from the packaged defaults")
    instructions = review_skill_instructions()
    modes = ("quick", "standard", "deep")
    originals = {}
    with tempfile.TemporaryDirectory(prefix="cwl-strix-review-skills-") as directory:
        skill_root = Path(directory)
        mode_root = skill_root / "scan_modes"
        mode_root.mkdir()
        try:
            for mode in modes:
                source = get_strix_resource_path("skills", "scan_modes", mode + ".md")
                original = source.read_bytes()
                original_body = load_skills(["scan_modes/" + mode]).get(mode, "")
                if not original or not original_body:
                    raise ValueError("Packaged Strix scan-mode instructions are unavailable")
                originals[mode] = original_body
                target = mode_root / (mode + ".md")
                target.write_bytes(original + b"\n\n" + instructions.encode("utf-8"))
                target.chmod(0o400)
            mode_root.chmod(0o500)
            skill_root.chmod(0o500)
            register_skill_dir(skill_root)
            # Strix skips unreadable skills and catches render errors. Reject a
            # partial prompt before any scanner/model work instead of accepting it.
            for mode in modes:
                for is_root in (True, False):
                    prompt = render_system_prompt(scan_mode=mode, is_root=is_root)
                    if instructions not in prompt or originals[mode] not in prompt:
                        raise ValueError("Strix did not render the complete mandatory skill bundle")
            yield instructions
        finally:
            skill_root.chmod(0o700)
            mode_root.chmod(0o700)


def main() -> None:
    """Register native skill extensions before entering the unchanged Strix CLI."""
    with registered_review_skills() as instructions:
        print(instructions.splitlines()[0], flush=True)
        from strix.interface.main import main as strix_main

        strix_main()


if __name__ == "__main__":
    main()
