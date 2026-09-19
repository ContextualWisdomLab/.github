"""Regression contract for the trusted-uv full-suite dependency closure."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/trusted-uv-materializer-quality-ci.yml")
NOEMA_LOCK = "requirements-noema-document-ci-hashes.txt"
OPENCODE_LOCK = "requirements-opencode-review-ci-hashes.txt"


def test_full_suite_installs_every_repository_test_dependency_lock() -> None:
    """The full pytest gate installs the Noema lock that owns defusedxml."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    pull_request_trigger = workflow.split("  push:\n", 1)[0]
    stable_python = workflow.split("- name: Set up current stable Python\n", 1)[1].split(
        "- name: Install hash-locked quality tooling\n", 1
    )[0]
    install = workflow.split("- name: Install hash-locked quality tooling\n", 1)[1].split(
        "- name: Run trusted uv tests with complete branch coverage\n", 1
    )[0]

    assert f'"{NOEMA_LOCK}"' in pull_request_trigger
    assert OPENCODE_LOCK in stable_python
    assert NOEMA_LOCK in stable_python
    assert f"-r {OPENCODE_LOCK}" in install
    assert f"-r {NOEMA_LOCK}" in install
