"""Exercise pinned content delivery and corruption failures before model work."""

import hashlib
import json
import os
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


@pytest.mark.parametrize("corruption", ["missing", "digest", "inventory", "identity", "symlink", "parent_symlink", "empty_host"])
def test_bundle_fails_closed_on_corruption(tmp_path, monkeypatch, corruption):
    """Missing, altered or redirected methods cannot silently produce a prompt."""
    root = tmp_path / "bundle"
    shutil.copytree(bundle.BUNDLE_ROOT, root)
    monkeypatch.setattr(bundle, "BUNDLE_ROOT", root)
    source = root / "references/review-and-refactor.md"
    manifest_path = root / "references/manifest.json"
    if corruption == "empty_host":
        (root / "SKILL.md").write_text(" \n")
    elif corruption == "missing":
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


def test_opencode_executes_trusted_shared_bundle_for_all_agents(tmp_path):
    """Execute shared instruction delivery without duplicating reviewer prompts."""
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
        assert (tmp_path / name).read_text() == name + " original\n"
    assert (tmp_path / "review-skill-instructions.md").read_text().startswith(expected + "\n")
    assert "Subagents may delegate further" in (tmp_path / "review-skill-instructions.md").read_text()


def test_noema_missing_bundle_never_opens_network(monkeypatch):
    """Unavailable mandatory methods prevent any provider request."""
    from scripts.ci import noema_review_gate as noema

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-only")
    monkeypatch.setattr(noema, "reject_private_llm_url", lambda _: None)

    def missing_bundle():
        raise FileNotFoundError("required method absent")

    def unexpected_opener(*_args):
        pytest.fail("network opener constructed without verified skills")

    monkeypatch.setattr(noema, "review_skill_instructions", missing_bundle)
    monkeypatch.setattr(noema.urllib.request, "build_opener", unexpected_opener)
    with pytest.raises(FileNotFoundError):
        noema.call_llm("owner/repo", 1, {}, "", False, "a" * 40)


def test_opencode_native_delegation_uses_shared_skills_and_readonly_policy(tmp_path):
    """Native and recursive subagents keep shared methods and isolation."""
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml").read_text()
    config_start = workflow.index('          jq -n --arg review_skill_path ')
    config_segment = workflow[config_start:].split('\n\n          gateway_config=', 1)[0]
    subprocess.run(
        ["bash", "-euc", config_segment], check=True,
        env={"PATH": os.environ["PATH"], "OPENCODE_REVIEW_WORKDIR": str(tmp_path)},
    )
    config = json.loads((tmp_path / "opencode.jsonc").read_text())
    assert config["instructions"] == [str(tmp_path / "review-skill-instructions.md")]
    assert config["permission"]["*"] == "deny"
    assert config["permission"]["task"] == "allow"
    for denied_tool in ("edit", "bash", "webfetch", "websearch", "lsp", "external_directory"):
        assert config["permission"][denied_tool] == "deny"
    for agent in config["agent"].values():
        assert agent["permission"]["task"] == "allow"
        assert "model" not in agent
    assert not config["agent"].get("general", {}).get("disable", False)
    assert not config["agent"].get("explore", {}).get("disable", False)
    assert config["model"] == config["small_model"] == "contextual-orchestrator/orchestrator/free"


def test_session_skill_sources_reach_every_complete_bundle():
    """Every pinned session skill and required textual reference reaches consumers."""
    content = bundle.review_skill_instructions()
    root = bundle.BUNDLE_ROOT / "references/session"
    manifest = json.loads((root / "session-manifest.json").read_bytes())
    for record in manifest["files"]:
        raw = (root / record["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert raw.decode() in content, "Missing full session source: " + record["source"]


@pytest.mark.parametrize("corruption", ["missing", "digest", "inventory", "identity", "symlink", "parent_symlink"])
def test_session_bundle_fails_closed_on_corruption(tmp_path, monkeypatch, corruption):
    """Session additions receive the same integrity and path checks as upstream methods."""
    root = tmp_path / "bundle"
    shutil.copytree(bundle.BUNDLE_ROOT, root)
    monkeypatch.setattr(bundle, "BUNDLE_ROOT", root)
    session_root = root / "references/session"
    source = session_root / "autoresearch/SKILL.md"
    manifest_path = session_root / "session-manifest.json"
    if corruption == "missing":
        source.unlink()
    elif corruption == "digest":
        source.write_bytes(source.read_bytes() + b"unapproved instruction")
    elif corruption in {"inventory", "identity"}:
        manifest = json.loads(manifest_path.read_bytes())
        if corruption == "inventory":
            manifest["files"].pop()
        else:
            manifest["files"][0]["source"] = "untrusted/replacement"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "symlink":
        other = tmp_path / "other.md"
        source.rename(other)
        source.symlink_to(other)
    else:
        other = tmp_path / "session"
        session_root.rename(other)
        session_root.symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, FileNotFoundError)):
        bundle.review_skill_instructions()
