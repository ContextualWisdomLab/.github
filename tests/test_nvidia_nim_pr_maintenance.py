"""Contract tests for hourly NVIDIA NIM review repair automation."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import pr_review_fix_scheduler_nim as nim_scheduler


SCHEDULER_WORKFLOW = Path(".github/workflows/nvidia-nim-pr-maintenance.yml")
AUTOFIX_WORKFLOW = Path(".github/workflows/nvidia-nim-pr-review-autofix.yml")


def test_wrapper_adds_nim_worker_when_caller_does_not_override() -> None:
    """The wrapper must route the shared scheduler to the NIM worker by default."""

    assert nim_scheduler._normalized_argv(["--self-test"]) == [
        "--self-test",
        "--autofix-workflow",
        nim_scheduler.NIM_AUTOFIX_WORKFLOW,
    ]


def test_wrapper_preserves_explicit_worker_argument() -> None:
    """An explicit worker argument must not be duplicated during normalization."""

    argv = ["--autofix-workflow", nim_scheduler.NIM_AUTOFIX_WORKFLOW, "--self-test"]
    assert nim_scheduler._normalized_argv(argv) == argv


def test_wrapper_applies_nim_dispatch_contract_and_restores_globals(monkeypatch) -> None:
    """The wrapper must apply NIM routing only for the duration of one invocation."""

    captured: dict[str, object] = {}
    original_workflow = nim_scheduler.scheduler.DEFAULT_AUTOFIX_WORKFLOW
    original_event = nim_scheduler.scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        captured["workflow"] = nim_scheduler.scheduler.DEFAULT_AUTOFIX_WORKFLOW
        captured["event"] = nim_scheduler.scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE
        return 17

    monkeypatch.setattr(nim_scheduler.scheduler, "main", fake_main)

    assert nim_scheduler.main(["--self-test"]) == 17
    assert captured == {
        "argv": [
            "--self-test",
            "--autofix-workflow",
            "nvidia-nim-pr-review-autofix.yml",
        ],
        "workflow": "nvidia-nim-pr-review-autofix.yml",
        "event": "nvidia-nim-pr-review-autofix",
    }
    assert nim_scheduler.scheduler.DEFAULT_AUTOFIX_WORKFLOW == original_workflow
    assert nim_scheduler.scheduler.AUTOFIX_REPOSITORY_DISPATCH_TYPE == original_event


def test_scheduler_runs_hourly_and_dispatches_one_bounded_repair() -> None:
    """The scheduler cadence and single-flight bounds must remain explicit."""

    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "23 * * * *"' in workflow
    assert "max_dispatches:" in workflow
    assert "retry_hours:" in workflow
    assert workflow.count('default: "1"') >= 2
    assert "MAX_DISPATCHES" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "nvidia-nim-pr-review-autofix.yml" in workflow
    assert "pr_review_fix_scheduler_nim.py --self-test" in workflow
    assert "--retry-hours \"$RETRY_HOURS\"" in workflow


def test_scheduler_declares_only_named_reusable_write_secrets() -> None:
    """Leaf callers need explicit GitHub write-token inputs, never blanket inheritance."""

    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")

    assert "PR_REVIEW_MERGE_TOKEN:" in workflow
    assert "OPENCODE_APPROVE_TOKEN:" in workflow
    assert workflow.count("required: false") >= 8
    assert "secrets: inherit" not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "NVIDIA_NIM_API_KEY" not in workflow


def test_scheduler_materializes_immutable_called_workflow_source() -> None:
    """Reusable callers must not redirect privileged scheduler code to a mutable ref."""

    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")

    assert "id-token: write" in workflow
    assert ".job_workflow_sha // .workflow_sha // empty" in workflow
    assert "Called workflow source did not resolve to an immutable SHA" in workflow
    assert (
        "ContextualWisdomLab/.github/.github/workflows/"
        "nvidia-nim-pr-maintenance.yml@*"
    ) in workflow
    assert "ref: ${{ steps.trusted_source.outputs.sha }}" in workflow
    assert "ref: main" not in workflow
    assert (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
        in workflow
    )


def test_autofix_uses_only_nvidia_nim_model_credentials() -> None:
    """Commercial repair inference must use NVIDIA NIM and never Copilot credentials."""

    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")

    assert "NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY is required" in workflow
    assert '"enabled_providers": ["nvidia-nim"]' in workflow
    assert '"baseURL": "https://integrate.api.nvidia.com/v1"' in workflow
    assert '"apiKey": "{env:NVIDIA_API_KEY}"' in workflow
    assert '"npm": "@ai-sdk/openai-compatible"' in workflow
    assert "nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "STRIX_GITHUB_MODELS_TOKEN" not in workflow
    assert "models.github.ai" not in workflow
    assert "github-models/" not in workflow


def test_autofix_remains_fail_closed_and_file_scoped() -> None:
    """The repair worker must reject missing credentials, moved heads, and broad edits."""

    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")

    required_contracts = (
        "No file-scoped actionable review paths were found",
        "OpenCode modified disallowed path",
        "PR head moved during repair; refusing to push",
        '"bash": "deny"',
        '"edit": "allow"',
        "git diff --check",
        "python3 -m py_compile",
        "Merge conflicts remain unresolved",
        "Conflict markers remain in repaired files",
        "same-repository heads",
    )
    for contract in required_contracts:
        assert contract in workflow


def test_autofix_source_and_toolchain_are_immutable() -> None:
    """The worker source, actions, and OpenCode binary must be integrity bounded."""

    workflow = AUTOFIX_WORKFLOW.read_text(encoding="utf-8")

    assert ".workflow_sha // empty" in workflow
    assert "ref: ${{ steps.trusted_source.outputs.sha }}" in workflow
    assert (
        "step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920"
        in workflow
    )
    assert (
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
        in workflow
    )
    assert 'OPENCODE_VERSION: "1.17.13"' in workflow
    assert (
        "OPENCODE_SHA256: "
        "157afa289d1a8d9372de0ce19ac726119b937a1f6b201808d46f06e4e59bb348"
        in workflow
    )
