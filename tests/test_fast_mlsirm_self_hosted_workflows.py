from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow_text(name: str) -> str:
    """Return one central fast-mlsirm workflow as UTF-8 text."""
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_fast_mlsirm_reusable_workflows_keep_isolated_runner_and_gate_contracts():
    for name in ("ci", "codeql", "statistical-studies", "hourly-pr-governance", "pypi-gap-guard"):
        text = workflow_text(f"fast-mlsirm-{name}.yml")
        assert "workflow_call:" in text
        assert "ubuntu-latest" not in text and "runs-on: ubuntu" not in text
        assert "group: CWL CI isolated" in text
        assert "labels: [self-hosted, Linux, X64]" in text
        assert f"group: central-fast-mlsirm-{name}-" in text
    ci = workflow_text("fast-mlsirm-ci.yml")
    assert 'python-version: ["3.12", "3.14"]' in ci
    assert 'test "${{ needs.python-matrix.result }}" = "success"' in ci
    assert "cargo test --locked --workspace" in ci
    assert "cargo test --locked --manifest-path crates/fast-mlsirm-py/Cargo.toml" in ci


def test_disabled_release_legs_fail_the_caller_instead_of_reporting_success():
    """Expose the intentional release hold as a failing required job."""
    text = workflow_text("fast-mlsirm-publish-pypi.yml")
    assert text.count("    if: ${{ false }}") == 2
    assert "  publication-disabled:\n" in text
    assert "    needs: [sdist]\n" in text
    assert "wheel legs are disabled; this release was not published" in text
    assert "      - run: exit 1\n" in text


def test_release_dependency_gate_passes_only_declared_provider_secrets():
    """Keep the PyPI credential outside the dependency-analysis boundary."""
    text = workflow_text("fast-mlsirm-publish-pypi.yml")
    gate = text.split("  dependency-gate:\n", 1)[1].split("\n  release-admission:\n", 1)[0]
    assert "secrets: inherit" not in gate
    for name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert f"      {name}: ${{{{ secrets.{name} }}}}" in gate
    assert "PIPY_TOKEN" not in gate


def test_gap_guard_fails_closed_when_release_inventory_cannot_be_read():
    """Authenticate gh and propagate release-list failures before gap decisions."""
    text = workflow_text("fast-mlsirm-pypi-gap-guard.yml")
    inventory = text.split("      - name: Resolve control-plane commit and PyPI inventory\n", 1)[1]
    inventory = inventory.split("\n      - name: Dispatch publish-pypi", 1)[0]
    assert "          GH_TOKEN: ${{ github.token }}\n" in inventory
    assert '            release_tags="$(' in inventory
    assert '            done <<< "$release_tags"' in inventory
    assert "            done < <(" not in inventory
