#!/usr/bin/env python3
"""Render OpenCode prompt templates without shell expansion."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys


def placeholder_values(environ: Mapping[str, str]) -> dict[str, str]:
    """Return the only workflow placeholders allowed in prompt templates."""
    return {
        "${PR_NUMBER}": environ.get("PR_NUMBER", ""),
        "${OPENCODE_SOURCE_WORKDIR}": environ.get("OPENCODE_SOURCE_WORKDIR", ""),
        "${GITHUB_WORKSPACE}": environ.get("GITHUB_WORKSPACE", ""),
        "${HEAD_SHA}": environ.get("HEAD_SHA", ""),
        "${RUN_ID}": environ.get("RUN_ID", ""),
        "${RUN_ATTEMPT}": environ.get("RUN_ATTEMPT", ""),
        "${OPENCODE_REVIEW_INTRO}": environ.get("OPENCODE_REVIEW_INTRO", ""),
        "${model_candidate}": environ.get("PROMPT_MODEL_CANDIDATE", ""),
    }


def render_prompt(text: str, environ: Mapping[str, str]) -> str:
    """Replace explicit placeholders while preserving shell metacharacters."""
    for old, new in placeholder_values(environ).items():
        text = text.replace(old, new)
    return text


def main(argv: list[str]) -> int:
    """Run the prompt template renderer."""
    if len(argv) != 1:
        print("usage: render_opencode_prompt_template.py PROMPT_FILE", file=sys.stderr)
        return 2

    prompt_path = Path(argv[0])
    text = prompt_path.read_text(encoding="utf-8")
    if prompt_path.name.startswith("opencode-review-contract-") and prompt_path.suffix == ".md":
        marker = "<!-- cwl-review-memory/v1 -->"
        if marker not in text.splitlines():
            protocol = Path(__file__).with_name("review_partition_protocol.md").read_text(encoding="utf-8")
            text = text.rstrip() + "\n\n" + protocol
    prompt_path.write_text(render_prompt(text, os.environ), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
