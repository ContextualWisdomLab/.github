"""Exercise pinned content delivery and corruption failures before model work."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.ci import review_skill_bundle as bundle


def test_complete_bundle_and_isolated_cli_ignore_target_cwd(tmp_path):
    """Every upstream byte reaches the prompt even from a hostile working tree."""
    content = bundle.review_skill_instructions()
    manifest = json.loads((bundle.BUNDLE_ROOT / "references/manifest.json").read_bytes())
    for record in manifest["files"]:
        raw = (bundle.BUNDLE_ROOT / "references" / record["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert raw.decode() in content
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/__init__.py").write_text('raise RuntimeError("untrusted import")')
    result = subprocess.run(
        [sys.executable, "-I", bundle.__file__], cwd=tmp_path,
        capture_output=True, text=True, check=True,
    )
    assert result.stdout == content + "\n"


@pytest.mark.parametrize("corruption", ["missing", "digest", "inventory", "identity", "symlink", "parent_symlink"])
def test_bundle_fails_closed_on_corruption(tmp_path, monkeypatch, corruption):
    """Missing, altered or redirected methods cannot silently produce a prompt."""
    root = tmp_path / "bundle"
    shutil.copytree(bundle.BUNDLE_ROOT, root)
    monkeypatch.setattr(bundle, "BUNDLE_ROOT", root)
    source = root / "references/review-and-refactor.md"
    manifest_path = root / "references/manifest.json"
    if corruption == "missing":
        source.unlink()
    elif corruption == "digest":
        source.write_bytes(source.read_bytes() + b"unapproved instruction")
    elif corruption in {"inventory", "identity"}:
        manifest = json.loads(manifest_path.read_bytes())
        if corruption == "inventory":
            manifest["files"].pop()
        else:
            manifest["commit"] = "main"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "symlink":
        other = tmp_path / "other.md"
        source.rename(other)
        source.symlink_to(other)
    else:
        other = tmp_path / "references"
        (root / "references").rename(other)
        (root / "references").symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, FileNotFoundError)):
        bundle.review_skill_instructions()


def test_opencode_executes_trusted_bundle_append_for_both_agents(tmp_path):
    """Execute the actual workflow shell segment, preserving each base prompt."""
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github/workflows/opencode-review-dispatch.yml").read_text()
    segment = workflow.split('          review_skill_instructions="', 1)[1]
    segment = 'review_skill_instructions="' + segment.split("\n\n", 1)[0]
    segment = "\n".join(line.removeprefix("          ") for line in segment.splitlines())
    for name in ("ci-review-prompt.md", "code-reviewer-prompt.md"):
        (tmp_path / name).write_text(name + " original\n")
    result = subprocess.run(
        ["bash", "-euc", segment], capture_output=True, text=True,
        env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin", "GITHUB_WORKSPACE": str(repo_root), "OPENCODE_REVIEW_WORKDIR": str(tmp_path)},
        check=True,
    )
    expected = bundle.review_skill_instructions()
    assert result.stdout == expected.splitlines()[0] + "\n"
    for name in ("ci-review-prompt.md", "code-reviewer-prompt.md"):
        assert (tmp_path / name).read_text() == name + " original\n\n" + expected + "\n"
