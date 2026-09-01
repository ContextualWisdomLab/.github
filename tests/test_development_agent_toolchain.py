"""Contract tests for the pinned development-agent toolchain action."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github" / "actions" / "development-agent-toolchain" / "action.yml"
INSTALLER = ROOT / ".github" / "actions" / "development-agent-toolchain" / "install.sh"

UPSTREAM_COMMITS = {
    "superpowers": "b36e0829c6d0140e93cfef2ca599b1b07d4a7797",
    "ponytail": "2ed6c52c9d7e5e56942508591085fd45dea277d3",
    "code-review-graph": "b58668751ab0c7670c078cf7cbd4d1f5b8e54f81",
    "ui-ux-pro-max-skill": "f23267105ad1f4ccd94af45d382584ad45b586f7",
    "Anti-Slop-UI": "ef9d06e9da3a7a902f89456b3a4c5c2601870eea",
}

MODEL_CREDENTIAL_NAMES = (
    "NOEMA_LLM_API_KEY",
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "CONTEXTUAL_ORCHESTRATOR_TOKEN",
)


def test_development_toolchain_pins_upstreams_and_uv() -> None:
    """Every remotely sourced development tool must have an immutable source pin."""
    action = ACTION.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d" in action
    assert 'version: "0.12.4"' in action
    for commit in UPSTREAM_COMMITS.values():
        assert commit in installer


def test_development_toolchain_keeps_runtime_assets_out_of_product_diffs() -> None:
    """Generated skills and indexes must stay runtime-only and untracked."""
    installer = INSTALLER.read_text(encoding="utf-8")

    assert ".opencode/skills/" in installer
    assert ".code-review-graph/" in installer
    assert ".codegraph/" in installer
    assert ".git/info/exclude" in installer


def test_development_toolchain_uses_locked_noninteractive_installers() -> None:
    """Third-party setup must be reproducible and must not execute package hooks."""
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev" in installer
    assert "npm ci --ignore-scripts" in installer
    assert "init --ai opencode --offline --force" in installer
    assert '"$CODEGRAPH_BIN" init -i' in installer


def test_development_toolchain_sanitizes_graph_server_environments() -> None:
    """MCP graph servers must not inherit model-provider credentials."""
    installer = INSTALLER.read_text(encoding="utf-8")

    assert installer.count("env -i") >= 2
    assert "serve --repo" in installer
    assert "serve --mcp" in installer
    for credential_name in MODEL_CREDENTIAL_NAMES:
        assert credential_name not in installer


def test_development_toolchain_installs_guidance_without_loading_plugins() -> None:
    """Credential-bearing OpenCode runs consume guidance, not third-party plugin hooks."""
    installer = INSTALLER.read_text(encoding="utf-8")

    assert 'copy_skill_tree "$SUPERPOWERS_SRC/skills"' in installer
    assert 'copy_skill_tree "$PONYTAIL_SRC/skills"' in installer
    assert "public-skills/SKILL.md" in installer
    assert "superpowers@git+" not in installer
    assert "@dietrichgebert/ponytail" not in installer
