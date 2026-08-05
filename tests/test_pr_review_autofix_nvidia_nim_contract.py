"""Contract tests for the scheduled OpenCode review-autofix trust boundary."""

from pathlib import Path
import subprocess


AUTOFIX_WORKFLOW = Path(".github/workflows/pr-review-autofix.yml")
FIX_SCHEDULER_WORKFLOW = Path(".github/workflows/pr-review-fix-scheduler.yml")
REVIEW_DISPATCH_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
REVIEW_DISPATCH_BLOB_SHA = "83f6830d5c21a324b4dbcd4e5c21a07968994b81"


def _workflow_text(path: Path) -> str:
    """Read one central workflow as UTF-8 text for static trust-boundary checks."""
    return path.read_text(encoding="utf-8")


def test_review_fix_scheduler_runs_once_each_hour() -> None:
    """Keep the actionable-review repair loop on the approved hourly cadence."""
    scheduler = _workflow_text(FIX_SCHEDULER_WORKFLOW)
    assert 'cron: "23 * * * *"' in scheduler
    assert 'cron: "23 */2 * * *"' not in scheduler


def test_scheduled_autofix_uses_only_nvidia_nim() -> None:
    """Require the write-capable OpenCode autofix agent to use NVIDIA NIM only."""
    workflow = _workflow_text(AUTOFIX_WORKFLOW)
    required_fragments = (
        '"model": "nvidia-nim/mistralai/mistral-nemotron"',
        '"small_model": "nvidia-nim/nvidia/nemotron-3-nano-30b-a3b"',
        '"enabled_providers": ["nvidia-nim"]',
        '"nvidia-nim": {',
        '"npm": "@ai-sdk/openai-compatible"',
        '"baseURL": "https://integrate.api.nvidia.com/v1"',
        '"apiKey": "{env:NVIDIA_API_KEY}"',
        'NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}',
        'MODEL: nvidia-nim/mistralai/mistral-nemotron',
    )
    for fragment in required_fragments:
        assert fragment in workflow, fragment
    forbidden_fragments = (
        'STRIX_GITHUB_MODELS_TOKEN:',
        'MODEL: github-models/',
        'USE_GITHUB_TOKEN:',
        '"enabled_providers": ["github-models"]',
        '"apiKey": "{env:STRIX_GITHUB_MODELS_TOKEN}"',
        '"baseURL": "https://models.github.ai/inference"',
        'COPILOT_GITHUB_TOKEN',
    )
    for fragment in forbidden_fragments:
        assert fragment not in workflow, fragment


def test_trusted_autofix_source_is_bound_to_dispatch_sha() -> None:
    """Prevent a moving default branch from replacing trusted autofix scripts."""
    workflow = _workflow_text(AUTOFIX_WORKFLOW)
    checkout_start = workflow.index("      - name: Checkout trusted autofix source")
    checkout_end = workflow.index(
        "      - name: Exchange OpenCode app token", checkout_start
    )
    checkout = workflow[checkout_start:checkout_end]
    assert "ref: ${{ github.sha }}" in checkout
    assert "ref: main" not in checkout
    assert "fetch-depth: 1" in checkout
    assert "persist-credentials: false" in checkout


def test_opencode_agent_denies_non_file_interactions() -> None:
    """Keep unattended repair bounded to local file inspection and edits."""
    workflow = _workflow_text(AUTOFIX_WORKFLOW)
    for permission_name in (
        "bash",
        "task",
        "skill",
        "question",
        "webfetch",
        "websearch",
        "lsp",
        "external_directory",
        "doom_loop",
    ):
        assert workflow.count(f'"{permission_name}": "deny"') == 2


def test_nvidia_nim_secret_is_scoped_to_agent_execution_steps() -> None:
    """Prevent the NVIDIA credential from leaking beyond the two OpenCode runs."""
    workflow = _workflow_text(AUTOFIX_WORKFLOW)
    binding = 'NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}'
    ordinary_start = workflow.index("      - name: Run OpenCode review autofix")
    ordinary_end = workflow.index("      - name: Validate changed files", ordinary_start)
    conflict_start = workflow.index(
        "      - name: Merge base branch and resolve conflicts with OpenCode"
    )
    assert workflow.count(binding) == 2
    assert binding in workflow[ordinary_start:ordinary_end]
    assert binding in workflow[conflict_start:]
    assert binding not in workflow[:ordinary_start]
    assert binding not in workflow[ordinary_end:conflict_start]


def test_model_subprocesses_receive_no_github_or_oidc_write_credentials() -> None:
    """Strip GitHub write and OIDC credentials from both OpenCode processes."""
    workflow = _workflow_text(AUTOFIX_WORKFLOW)
    ordinary_start = workflow.index("      - name: Run OpenCode review autofix")
    ordinary_end = workflow.index("      - name: Validate changed files", ordinary_start)
    ordinary = workflow[ordinary_start:ordinary_end]
    conflict_start = workflow.index(
        "      - name: Merge base branch and resolve conflicts with OpenCode"
    )
    conflict = workflow[conflict_start:]
    sanitized_invocation = (
        "env -u GITHUB_TOKEN -u GH_TOKEN "
        "-u ACTIONS_ID_TOKEN_REQUEST_TOKEN -u ACTIONS_ID_TOKEN_REQUEST_URL"
    )
    assert "GITHUB_TOKEN:" not in ordinary
    assert "GH_TOKEN:" not in ordinary
    assert sanitized_invocation in ordinary
    assert sanitized_invocation in conflict
    assert workflow.count(sanitized_invocation) == 2


def test_missing_nvidia_nim_secret_fails_closed_before_model_execution() -> None:
    """Reject an empty model credential instead of falling back to another provider."""
    workflow = _workflow_text(AUTOFIX_WORKFLOW)
    guard = (
        'if [ -z "${NVIDIA_API_KEY:-}" ]; then\n'
        '            echo "::error::NVIDIA_NIM_API_KEY is required for scheduled '
        'OpenCode autofix."\n'
        "            exit 1\n"
        "          fi"
    )
    ordinary_start = workflow.index("      - name: Run OpenCode review autofix")
    ordinary_end = workflow.index("      - name: Validate changed files", ordinary_start)
    conflict_start = workflow.index(
        "      - name: Merge base branch and resolve conflicts with OpenCode"
    )
    assert workflow.count(guard) == 2
    assert guard in workflow[ordinary_start:ordinary_end]
    assert guard in workflow[conflict_start:]


def test_independent_review_agent_key_system_is_unchanged() -> None:
    """Pin the existing read-only reviewer workflow byte-for-byte."""
    result = subprocess.run(
        ["git", "hash-object", str(REVIEW_DISPATCH_WORKFLOW)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == REVIEW_DISPATCH_BLOB_SHA
    assert "pr-review-autofix" not in _workflow_text(REVIEW_DISPATCH_WORKFLOW)
