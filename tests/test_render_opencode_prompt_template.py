import runpy
import sys

import pytest

from scripts.ci.render_opencode_prompt_template import main, render_prompt


def test_render_prompt_replaces_only_explicit_placeholders():
    text = (
        "${OPENCODE_REVIEW_INTRO}\n"
        "Review PR #${PR_NUMBER} in ${OPENCODE_SOURCE_WORKDIR} with "
        "${model_candidate}.\n"
        "`python3 scripts/ci/sandboxed_verify.py --repo-root "
        '"$OPENCODE_SOURCE_WORKDIR" -- <verification command>`\n'
        "$(echo should_not_run)\n"
    )

    rendered = render_prompt(
        text,
        {
            "PR_NUMBER": "193",
            "OPENCODE_SOURCE_WORKDIR": "/tmp/pr-head",
            "OPENCODE_REVIEW_INTRO": "Use the shared review template.",
            "PROMPT_MODEL_CANDIDATE": "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5",
        },
    )

    assert rendered.startswith("Use the shared review template.")
    assert "Review PR #193 in /tmp/pr-head" in rendered
    assert "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" in rendered
    assert '"$OPENCODE_SOURCE_WORKDIR"' in rendered
    assert "`python3 scripts/ci/sandboxed_verify.py" in rendered
    assert "$(echo should_not_run)" in rendered


def test_main_renders_prompt_file(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("${OPENCODE_REVIEW_INTRO}\nPR ${PR_NUMBER} in ${OPENCODE_SOURCE_WORKDIR}\n", encoding="utf-8")
    monkeypatch.setenv("PR_NUMBER", "193")
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", "/tmp/pr-head")
    monkeypatch.setenv("OPENCODE_REVIEW_INTRO", "Intro line")

    assert main([str(prompt_file)]) == 0

    assert prompt_file.read_text(encoding="utf-8") == "Intro line\nPR 193 in /tmp/pr-head\n"


def test_main_rejects_wrong_arg_count(capsys):
    assert main([]) == 2

    assert "usage: render_opencode_prompt_template.py PROMPT_FILE" in capsys.readouterr().err


def test_module_entrypoint(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("${HEAD_SHA}\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["render_opencode_prompt_template.py", str(prompt_file)],
    )
    monkeypatch.setenv("HEAD_SHA", "abc123")

    module = sys.modules.pop("scripts.ci.render_opencode_prompt_template", None)
    with pytest.raises(SystemExit) as exc_info:
        try:
            runpy.run_module("scripts.ci.render_opencode_prompt_template", run_name="__main__")
        finally:
            if module is not None:
                sys.modules["scripts.ci.render_opencode_prompt_template"] = module

    assert exc_info.value.code == 0
    assert prompt_file.read_text(encoding="utf-8") == "abc123\n"
