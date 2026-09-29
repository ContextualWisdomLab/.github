"""Execute the real CodeQL scope step against complete, exact Git inventories."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import textwrap

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/codeql-pr.yml"


def _git(repo: Path, *args: str) -> str:
    """Run Git only against an isolated fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, shell=False, timeout=30,
    ).stdout.strip()


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Commit content using a fixture-local identity, not the operator's config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Inventory test")
    _git(repo, "config", "user.email", "inventory-test@example.invalid")
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--allow-empty", "-qm", "fixture")
    return repo


def _scope(tmp_path: Path, repo: Path, changed: list[str], *,
           expected_count: int | None = None, head: str | None = None,
           git_failure: bool = False) -> tuple[str, str]:
    """Stub the PR-file API, but execute the production shell and real Git."""
    block = WORKFLOW.read_text(encoding="utf-8").split(
        "      - name: Classify changed paths\n", 1
    )[1].split("\n  analyze-head:", 1)[0]
    script = textwrap.dedent(block.split("        run: |\n", 1)[1])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_CHANGED"\n', encoding="utf-8")
    gh.chmod(0o755)
    if git_failure:
        git = bin_dir / "git"
        git.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
        git.chmod(0o755)
    output = tmp_path / "scope-output"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               GH_TOKEN="test-only", REPO="test/content", PR="1",
               EXPECTED_FILES=str(len(changed) if expected_count is None else expected_count),
               PR_HEAD_SHA=_git(repo, "rev-parse", "HEAD") if head is None else head,
               FIXTURE_CHANGED="\n".join(changed), GITHUB_OUTPUT=str(output))
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=repo, env=env, check=True, capture_output=True, text=True,
        shell=False, timeout=30,
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return values["code"], result.stdout


def test_evaluation_data_only_head_does_not_dispatch_a_fictional_actions_scan(tmp_path):
    """Reproduce korean-writing-skills#4 without asserting a clean security scan."""
    files = {"README.md": "# Skills\n", ".gitignore": "local/\n",
             "evaluations/fixtures/K14/freeze.json": "{}\n",
             "docs/source-ledger.md": "Sources\n"}
    repo = _repo(tmp_path, files)
    code, log = _scope(tmp_path, repo, list(files))
    assert code == "false"
    assert "CodeQL not applicable" in log
    assert "security" in log


@pytest.mark.parametrize("name", [
    "src/main.py", "src/main.js", "src/main.ts", "src/Main.java", "src/main.rs",
    "src/main.go", "src/main.c", "src/Main.cs", "src/main.rb", "src/main.swift",
    ".github/workflows/test.yml", "action.yaml", "script.sh", "payload.svg",
    "package.json", "unknown.dat", "LICENSE.py",
])
def test_json_change_does_not_hide_any_non_content_file(tmp_path, name):
    """All source and unknown kinds remain on the pre-existing scanning path."""
    files = {"README.md": "# Skills\n", "evaluations/freeze.json": "{}\n", name: "x\n"}
    repo = _repo(tmp_path, files)
    code, _ = _scope(tmp_path, repo, ["evaluations/freeze.json"])
    assert code == "true"


@pytest.mark.parametrize("mode", ["executable", "symlink", "submodule"])
def test_non_regular_blob_modes_cannot_obtain_content_exemption(tmp_path, mode):
    """Do not follow links or discard executable/submodule evidence."""
    repo = _repo(tmp_path, {"README.md": "# Skills\n", "evaluations/freeze.json": "{}\n"})
    if mode == "executable":
        _git(repo, "update-index", "--chmod=+x", "README.md")
    elif mode == "symlink":
        (repo / "linked.md").symlink_to("README.md")
        _git(repo, "add", "linked.md")
    else:
        _git(repo, "update-index", "--add", "--cacheinfo",
             "160000", _git(repo, "rev-parse", "HEAD"), "nested.md")
    _git(repo, "commit", "-qm", "non-regular fixture")
    code, _ = _scope(tmp_path, repo, ["evaluations/freeze.json"])
    assert code == "true"


def test_missing_or_incorrect_pr_file_count_cannot_obtain_exemption(tmp_path):
    """An incomplete API response keeps the original fail-closed scan policy."""
    repo = _repo(tmp_path, {"README.md": "# Skills\n", "evaluations/freeze.json": "{}\n"})
    code, _ = _scope(tmp_path, repo, ["evaluations/freeze.json"], expected_count=2)
    assert code == "true"


@pytest.mark.parametrize("head", ["", "main", "0" * 40, "a" * 39, "A" * 40])
def test_inventory_must_bind_to_canonical_expected_head(tmp_path, head):
    """Neither a mutable ref nor an absent/wrong object is eligibility proof."""
    repo = _repo(tmp_path, {"README.md": "# Skills\n", "evaluations/freeze.json": "{}\n"})
    code, _ = _scope(tmp_path, repo, ["evaluations/freeze.json"], head=head)
    assert code == "true"


def test_git_read_failure_cannot_obtain_exemption(tmp_path):
    """A failed local authority read is not an empty, safe repository."""
    repo = _repo(tmp_path, {"README.md": "# Skills\n", "evaluations/freeze.json": "{}\n"})
    code, _ = _scope(tmp_path, repo, ["evaluations/freeze.json"], git_failure=True)
    assert code == "true"


def test_sparse_checkout_does_not_hide_source_from_inventory(tmp_path):
    """Read the commit tree rather than the visible or sparse working directory."""
    repo = _repo(tmp_path, {"README.md": "# Skills\n", "evaluations/freeze.json": "{}\n",
                            "src/main.py": "print('fixture')\n"})
    (repo / "src/main.py").unlink()
    code, _ = _scope(tmp_path, repo, ["evaluations/freeze.json"])
    assert code == "true"


def test_named_required_job_and_existing_dispatch_guards_are_preserved():
    """No empty matrix, trigger filter, job-level bypass, or forged verdict."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    analyze = workflow.split("\n  analyze-head:\n", 1)[1].split("\n  dispatch-current-head:", 1)[0]
    assert not re.search(r"(?m)^    if:", analyze)
    assert analyze.count("needs.detect-languages.outputs.code == 'true'") == 2
    assert "name: CodeQL compatibility analysis (${{ matrix.language }})" in analyze
    assert "matrix='[{\"language\":\"actions\",\"build-mode\":\"none\"}]'" in workflow
    coordinator = workflow.split("\n  dispatch-current-head:", 1)[1]
    assert "&& needs.detect-languages.outputs.code == 'true'" in coordinator
    assert "GHAS identity and preserved SARIF" in workflow


def _content_predicate():
    """Load just the pure classifier from the production inline Python."""
    import ast

    source = WORKFLOW.read_text(encoding="utf-8")
    embedded = textwrap.dedent(source.split("<<'PY_CONTENT_ONLY'\n", 1)[1].split(
        "          PY_CONTENT_ONLY\n", 1
    )[0])
    tree = ast.parse(embedded)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "content_only")
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(WORKFLOW), "exec"), namespace)
    return namespace["content_only"]


@pytest.mark.parametrize("raw", [
    b"", b"\0", b"100644 blob " + b"a" * 40 + b"\tREADME.md",
    b"100644 blob " + b"a" * 39 + b"\tREADME.md\0",
    b"100644 blob " + b"A" * 40 + b"\tREADME.md\0",
    b"100644 tree " + b"a" * 40 + b"\tREADME.md\0",
    b"100644 blob " + b"a" * 40 + b" README.md\0",
    b"100644 blob " + b"a" * 40 + b"\t../README.md\0",
    b"100644 blob " + b"a" * 40 + b"\t/README.md\0",
    b"100644 blob " + b"a" * 40 + b"\tnested//README.md\0",
    b"100644 blob " + b"a" * 40 + b"\tline\nbreak.md\0",
    b"100644 blob " + b"a" * 40 + b"\ttab\tname.md\0",
])
def test_malformed_or_incomplete_inventory_is_not_content_evidence(raw):
    """Do not reinterpret malformed framing, metadata, or paths as admission."""
    assert _content_predicate()(raw) is False


def test_unicode_content_paths_are_accepted_without_logging_the_paths():
    """Ordinary Korean filenames need no ASCII-only restriction."""
    raw = b"100644 blob " + b"a" * 40 + b"\t" + "자료/근거.md".encode() + b"\0"
    assert _content_predicate()(raw) is True
