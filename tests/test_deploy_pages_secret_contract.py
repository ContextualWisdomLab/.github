"""Least-privilege and input-safety contracts for Pages deployment."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/deploy-pages.yml"
POLICY_PATH = REPO_ROOT / "docs/doctoring/deploy-pages-secret-contract.md"
INFRA_GUIDE_PATH = REPO_ROOT / "infra/cloudflare/README.md"
EXPECTED_SECRETS = {"CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}
SECRET_DECLARATION_RE = re.compile(
    r"^      ([A-Z][A-Z0-9_]+):[ \t]*(?:#.*)?$", re.MULTILINE
)
INHERITED_SECRETS_RE = re.compile(
    r"""(?m)^[ \t]*secrets[ \t]*:[ \t]*(?:inherit|["']inherit["'])[ \t]*(?:#.*)?$"""
)


def workflow_text() -> str:
    """Return the authoritative reusable Pages workflow text."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def deployment_input_validation_script() -> str:
    """Return the executable deployment-input validator from the workflow."""
    workflow = workflow_text()
    marker = "      - name: Validate deployment inputs\n"
    assert marker in workflow
    step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    run_marker = "        run: |\n"
    assert run_marker in step
    return textwrap.dedent(step.split(run_marker, 1)[1])


def run_deployment_input_validation(
    tmp_path: Path,
    *,
    project_name: str = "safe-project",
    build_dir: str = "./public",
    custom_domain: str = "www.example.com",
) -> subprocess.CompletedProcess[str]:
    """Execute the production validator against one isolated caller workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "public").mkdir()
    output = tmp_path / "github-output.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_WORKSPACE": str(workspace),
            "GITHUB_OUTPUT": str(output),
            "RAW_PROJECT_NAME": project_name,
            "RAW_BUILD_DIR": build_dir,
            "RAW_CUSTOM_DOMAIN": custom_domain,
        }
    )
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", deployment_input_validation_script()],
        cwd=workspace,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_deploy_pages_declares_only_required_cloudflare_secrets() -> None:
    """Declare and consume only the two Cloudflare names in this workflow."""
    workflow = workflow_text()
    call_contract = workflow.split("  workflow_call:\n", 1)[1].split(
        "\npermissions:\n", 1
    )[0]

    assert "    secrets:\n" in call_contract
    for secret_name in EXPECTED_SECRETS:
        secret_contract = re.search(
            rf"^      {re.escape(secret_name)}:\n(?P<body>(?:        .*\n?)+)",
            call_contract,
            re.MULTILINE,
        )
        assert secret_contract is not None
        assert "required: true" in secret_contract.group("body")
    declared = set(SECRET_DECLARATION_RE.findall(call_contract))
    assert declared == EXPECTED_SECRETS
    referenced = set(re.findall(r"secrets\.([A-Z][A-Z0-9_]+)", workflow))
    assert referenced == EXPECTED_SECRETS


@pytest.mark.parametrize(
    "declaration",
    (
        "      EXTRA_SECRET:\n",
        "      EXTRA_SECRET:   \n",
        "      EXTRA_SECRET: # comment\n",
        "      EXTRA_SECRET:\t# comment\n",
    ),
)
def test_declared_secret_parser_covers_valid_yaml_comment_variants(
    declaration: str,
) -> None:
    """Detect an added reusable secret even when YAML adds spacing or comments."""
    assert set(SECRET_DECLARATION_RE.findall(declaration)) == {"EXTRA_SECRET"}


def test_deploy_pages_examples_map_secrets_explicitly() -> None:
    """Prevent executable central examples from restoring blanket inheritance."""
    workflow = workflow_text()
    documents = (
        POLICY_PATH.read_text(encoding="utf-8"),
        INFRA_GUIDE_PATH.read_text(encoding="utf-8"),
    )
    examples = [workflow]

    for document in documents:
        fenced_yaml = [
            block.split("\n```", 1)[0]
            for block in document.split("```yaml\n")[1:]
            if "\n```" in block
        ]
        assert fenced_yaml
        examples.extend(fenced_yaml)

    for example in examples:
        assert INHERITED_SECRETS_RE.search(example) is None
        assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in example
        assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in example


@pytest.mark.parametrize(
    "mapping",
    (
        "secrets: inherit",
        "secrets:    inherit",
        "  secrets: inherit # caller shortcut",
        "secrets: 'inherit'",
        'secrets: "inherit" # caller shortcut',
    ),
)
def test_inherit_detector_covers_yaml_spacing_quote_and_comment_variants(
    mapping: str,
) -> None:
    """Recognize every supported scalar spelling of forbidden blanket inheritance."""
    assert INHERITED_SECRETS_RE.search(mapping) is not None


def test_deploy_pages_policy_records_inherit_platform_boundary() -> None:
    """Document GitHub inheritance limits without weakening CWL caller policy."""
    policy = " ".join(POLICY_PATH.read_text(encoding="utf-8").split())

    for required_boundary in (
        "Approved CWL callers MUST map them explicitly and MUST NOT use `secrets: inherit`",
        "not a GitHub runtime allowlist",
        "can be referenced by the called workflow even when they are not declared under `on.workflow_call.secrets`",
        "cannot disable GitHub's inheritance keyword",
        "leaf migration defect",
    ):
        assert required_boundary in policy


def test_deploy_pages_missing_secret_diagnostic_does_not_print_values() -> None:
    """Keep the defense-in-depth guard fail-closed and value-free."""
    workflow = workflow_text()
    guard = workflow.split("      - name: Guard secrets present\n", 1)[1].split(
        "\n      - name:", 1
    )[0]

    assert 'if [ -z "${CF_API_TOKEN}" ] || [ -z "${CF_ACCOUNT_ID}" ]; then' in guard
    assert "Caller must map both declared reusable-workflow secrets." in guard
    assert 'echo "${CF_API_TOKEN}"' not in guard
    assert 'echo "${CF_ACCOUNT_ID}"' not in guard


def test_deploy_pages_validates_inputs_before_command_or_url_use() -> None:
    """Only validated outputs may reach Wrangler, Cloudflare URLs, or summaries."""
    workflow = workflow_text()
    validate_at = workflow.index("      - name: Validate deployment inputs\n")
    deploy_at = workflow.index("      - name: Deploy to Cloudflare Pages (wrangler)\n")
    attach_at = workflow.index("      - name: Attach custom domain (idempotent)\n")
    summary_at = workflow.index("      - name: Summary\n")
    assert validate_at < deploy_at < attach_at < summary_at

    validator = workflow[validate_at:deploy_at]
    for raw_name in ("project_name", "build_dir", "custom_domain"):
        assert f"RAW_{raw_name.upper()}: ${{{{ inputs.{raw_name} }}}}" in validator

    deployment = workflow[deploy_at:attach_at]
    assert "${{ inputs.project_name }}" not in deployment
    assert "${{ inputs.build_dir }}" not in deployment
    assert "steps.deploy_inputs.outputs.project_name" in deployment
    assert "steps.deploy_inputs.outputs.build_dir" in deployment

    post_validation = workflow[attach_at:]
    for raw_name in ("project_name", "build_dir", "custom_domain"):
        assert f"${{{{ inputs.{raw_name} }}}}" not in post_validation
    assert "steps.deploy_inputs.outputs.project_name" in post_validation
    assert "steps.deploy_inputs.outputs.custom_domain" in post_validation


def test_deploy_pages_validator_accepts_bounded_canonical_inputs(tmp_path: Path) -> None:
    """Accept a normal project, repository-local build directory, and DNS name."""
    completed = run_deployment_input_validation(tmp_path)
    assert completed.returncode == 0, completed.stderr
    output = (tmp_path / "github-output.txt").read_text(encoding="utf-8")
    assert "project_name=safe-project\n" in output
    assert "build_dir=public\n" in output
    assert "custom_domain=www.example.com\n" in output


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("project_name", "safe project"),
        ("project_name", "safe;project"),
        ("project_name", "safe/project"),
        ("project_name", "--help"),
        ("project_name", "safe.project"),
        ("build_dir", "../public"),
        ("build_dir", "/tmp/public"),
        ("build_dir", "public --branch=evil"),
        ("build_dir", "public;echo-pwn"),
        ("custom_domain", "example.com/path"),
        ("custom_domain", "example.com?x=1"),
        ("custom_domain", "bad domain.example"),
        ("custom_domain", "-bad.example"),
        ("custom_domain", "bad-.example"),
    ),
)
def test_deploy_pages_validator_rejects_argument_and_path_injection(
    tmp_path: Path, field: str, value: str
) -> None:
    """Reject command, option, traversal, URL-path, and malformed-host inputs."""
    kwargs = {field: value}
    completed = run_deployment_input_validation(tmp_path, **kwargs)
    assert completed.returncode != 0
    assert "::error::Invalid Cloudflare Pages deployment input." in completed.stderr


def test_deploy_pages_validator_rejects_symlink_escape(tmp_path: Path) -> None:
    """A caller build-directory symlink cannot escape the checked-out workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "public").symlink_to(outside, target_is_directory=True)
    output = tmp_path / "github-output.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "GITHUB_WORKSPACE": str(workspace),
            "GITHUB_OUTPUT": str(output),
            "RAW_PROJECT_NAME": "safe-project",
            "RAW_BUILD_DIR": "./public",
            "RAW_CUSTOM_DOMAIN": "",
        }
    )
    completed = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", deployment_input_validation_script()],
        cwd=workspace,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "::error::Invalid Cloudflare Pages deployment input." in completed.stderr
