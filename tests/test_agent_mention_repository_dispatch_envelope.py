"""Contracts for the bounded OpenCode repository-dispatch envelope."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"
WRAPPER_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"
SCHEDULER_WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"
QUALITY_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router-quality-ci.yml"
SCHEMA = "cwl.agent-invocation/v2"
ENVELOPE_KEYS = {"schema", "claim", "agent_invocation_key"}


def _load_router() -> ModuleType:
    """Load the mention router from the repository under test."""

    module_name = "agent_mention_repository_dispatch_envelope"
    spec = importlib.util.spec_from_file_location(module_name, ROUTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _request(router: ModuleType):
    """Return one complete OpenCode mention request."""

    return router.MentionRequest(
        repository="ContextualWisdomLab/example",
        pull_request_number=17,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="main",
        comment_id=91,
        actor="maintainer",
        agents=("opencode-agent",),
        pull_request_base_sha="b" * 40,
    )


def _named_step(workflow: str, name: str) -> str:
    """Return one exact named workflow step."""

    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    try:
        end = workflow.index("\n      - name:", start + len(marker))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


def _python_heredoc(step: str) -> str:
    """Return executable Python from one workflow heredoc."""

    marker = "python3 - <<'PYTHON'\n"
    start = step.index(marker) + len(marker)
    end = step.index("\n          PYTHON", start)
    return textwrap.dedent(step[start:end])


def _run_python_contract(
    code: str, environment: dict[str, str]
) -> subprocess.CompletedProcess:
    """Execute one extracted workflow validator with an isolated environment."""

    return subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **environment},
    )


def _rebind_invocation_key(payload: dict[str, object]) -> None:
    """Recompute the canonical claim digest after an intentional claim mutation."""

    canonical = json.dumps(
        payload["claim"],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["agent_invocation_key"] = hashlib.sha256(canonical).hexdigest()


def test_router_emits_three_key_versioned_envelope_without_changing_claim_key() -> None:
    """Keep the transport bounded while preserving existing ledger identities."""

    router = _load_router()
    request = _request(router)
    body = router.opencode_payload(request)
    payload = body["client_payload"]

    assert body["event_type"] == "agent-mention-opencode"
    assert set(payload) == ENVELOPE_KEYS
    assert len(payload) == 3
    assert payload["schema"] == SCHEMA
    assert payload["claim"] == router.agent_invocation_claim(
        request, "opencode-agent"
    )
    assert payload["agent_invocation_key"] == (
        "8c73b6aa8ca5ef7b610b997e6913b71bfad29e74330836263087617fb3d0b9ff"
    )
    assert router.agent_ledger_artifact_name(request, "opencode-agent") == (
        "cwl-agent-invocation-"
        "8c73b6aa8ca5ef7b610b997e6913b71bfad29e74330836263087617fb3d0b9ff"
    )
    assert len(json.dumps(payload, separators=(",", ":"))) <= 65_535


def test_router_rejects_an_oversized_first_hop_before_calling_github() -> None:
    """The producer enforces GitHub's size contract before any API request."""

    router = _load_router()
    oversized = replace(_request(router), actor="a" * 70_000)

    with pytest.raises(ValueError, match="repository dispatch exceeds GitHub limits"):
        router.opencode_payload(oversized)


def test_wrapper_validates_and_reuses_the_same_bounded_envelope_before_ledger() -> None:
    """Validate the complete second hop before claiming an immutable artifact."""

    workflow = WRAPPER_WORKFLOW.read_text(encoding="utf-8")
    validate = _named_step(
        workflow,
        "Validate exact invocation payload and prepare scheduler request",
    )
    forward = _named_step(
        workflow,
        "Forward once to the authoritative review-only scheduler",
    )

    assert "github.event.client_payload.claim.repository" in workflow
    assert "github.event.client_payload.claim.pr_number" in workflow
    assert "PAYLOAD_SCHEMA: ${{ github.event.client_payload.schema || '' }}" in workflow
    assert "set(envelope)" in validate
    for key in sorted(ENVELOPE_KEYS):
        assert f'"{key}"' in validate
    assert "set(claim)" in validate
    assert "hmac.compare_digest" in validate
    assert "65_535" in validate
    assert '"event_type": "merge-scheduler-agent-review-v2"' in validate
    assert '"client_payload": envelope' in validate
    assert workflow.index(
        "Validate exact invocation payload and prepare scheduler request"
    ) < workflow.index("Inspect exact-name Actions artifact ledger")
    assert '--input "$SCHEDULER_REQUEST_FILE"' in forward
    assert "client_payload:" not in forward


def test_wrapper_executes_the_validated_envelope_as_the_exact_second_hop(
    tmp_path: Path,
) -> None:
    """The materialized scheduler request reuses the exact three-key payload."""

    router = _load_router()
    payload = router.opencode_payload(_request(router))["client_payload"]
    workflow = WRAPPER_WORKFLOW.read_text(encoding="utf-8")
    code = _python_heredoc(
        _named_step(
            workflow,
            "Validate exact invocation payload and prepare scheduler request",
        )
    )
    environment_file = tmp_path / "github-env"
    completed = _run_python_contract(
        code,
        {
            "CLIENT_PAYLOAD_JSON": json.dumps(payload),
            "GITHUB_ENV": str(environment_file),
            "INVOCATION_KEY": payload["agent_invocation_key"],
            "PAYLOAD_SCHEMA": payload["schema"],
            "RUNNER_TEMP": str(tmp_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    request_path = tmp_path / "agent-review-scheduler-request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request == {
        "event_type": "merge-scheduler-agent-review-v2",
        "client_payload": payload,
    }
    assert len(request["client_payload"]) == 3
    assert request_path.stat().st_size <= 65_535
    assert f"SCHEDULER_REQUEST_FILE={request_path}" in environment_file.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("mutation", "error_fragment"),
    [
        ("extra-envelope-field", "invalid OpenCode invocation envelope"),
        ("missing-claim-field", "invalid OpenCode invocation claim fields"),
        ("wrong-boolean-type", "invalid enable_auto_merge flag"),
        ("altered-bound-field", "invocation key does not match canonical payload"),
        ("unsupported-schema", "unsupported OpenCode invocation schema"),
        ("policy-violating-claim", "violates review-only policy"),
        ("invalid-repository", "invalid repository"),
        ("invalid-head-sha", "invalid head SHA"),
        ("invalid-base-sha", "invalid base SHA"),
        ("invalid-base-branch", "invalid base branch"),
        ("invalid-actor", "invalid actor"),
    ],
)
def test_wrapper_rejects_malformed_or_unbound_envelopes_before_materialization(
    tmp_path: Path,
    mutation: str,
    error_fragment: str,
) -> None:
    """Unknown, malformed, or key-mismatched claims fail before ledger access."""

    router = _load_router()
    payload = deepcopy(router.opencode_payload(_request(router))["client_payload"])
    if mutation == "extra-envelope-field":
        payload["extra"] = "rejected"
    elif mutation == "missing-claim-field":
        del payload["claim"]["base_sha"]
    elif mutation == "wrong-boolean-type":
        payload["claim"]["enable_auto_merge"] = "false"
    elif mutation == "altered-bound-field":
        payload["claim"]["head_sha"] = "c" * 40
    elif mutation == "unsupported-schema":
        payload["schema"] = "cwl.agent-invocation/v3"
    elif mutation == "policy-violating-claim":
        payload["claim"]["update_branches"] = True
    elif mutation == "invalid-repository":
        payload["claim"]["repository"] = "OtherOrg/example"
    elif mutation == "invalid-head-sha":
        payload["claim"]["head_sha"] = "z" * 40
    elif mutation == "invalid-base-sha":
        payload["claim"]["base_sha"] = "z" * 40
    elif mutation == "invalid-base-branch":
        payload["claim"]["base_branch"] = "-main"
    elif mutation == "invalid-actor":
        payload["claim"]["actor"] = "invalid_actor"
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(mutation)

    if mutation in {
        "policy-violating-claim",
        "invalid-repository",
        "invalid-head-sha",
        "invalid-base-sha",
        "invalid-base-branch",
        "invalid-actor",
    }:
        _rebind_invocation_key(payload)

    workflow = WRAPPER_WORKFLOW.read_text(encoding="utf-8")
    code = _python_heredoc(
        _named_step(
            workflow,
            "Validate exact invocation payload and prepare scheduler request",
        )
    )
    completed = _run_python_contract(
        code,
        {
            "CLIENT_PAYLOAD_JSON": json.dumps(payload),
            "GITHUB_ENV": str(tmp_path / "github-env"),
            "INVOCATION_KEY": payload["agent_invocation_key"],
            "PAYLOAD_SCHEMA": payload["schema"],
            "RUNNER_TEMP": str(tmp_path),
        },
    )

    assert completed.returncode != 0
    assert error_fragment in completed.stderr
    assert not (tmp_path / "agent-review-scheduler-request.json").exists()


def test_scheduler_has_strict_v2_and_explicit_legacy_dispatch_paths() -> None:
    """The dedicated review event must not fall through generic flat defaults."""

    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    targeted = _named_step(workflow, "Validate targeted repository dispatch")
    inspect = _named_step(workflow, "Inspect PR review and merge queue")

    assert "types: [merge-scheduler, merge-scheduler-agent-review-v2]" in workflow
    assert "github.event.client_payload.claim.repository" in workflow
    assert "github.event.client_payload.claim.pr_number" in workflow
    assert (
        'os.environ["GITHUB_EVENT_ACTION"] == "merge-scheduler-agent-review-v2"'
        in targeted
    )
    assert f'EXPECTED_SCHEMA="{SCHEMA}"' in targeted
    assert "set(envelope)" in targeted
    assert "set(claim)" in targeted
    assert "hmac.compare_digest" in targeted
    assert 'live_base_sha="$(jq -r \'.base.sha // empty\'' in targeted
    assert '"$TARGET_HEAD_SHA_INPUT" != "$live_head_sha"' in targeted
    assert '"$TARGET_BASE_SHA_INPUT" != "$live_base_sha"' in targeted
    assert "--expected-head-sha" in inspect
    assert "--expected-base-sha" in inspect
    assert "--expected-base-branch" in inspect
    concurrency = workflow.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    assert "github.event.client_payload.agent_invocation_key" in concurrency
    assert "github.event.action != 'merge-scheduler-agent-review-v2'" in concurrency
    assert "github.run_id" in concurrency


def test_scheduler_executes_strict_v2_validation_and_keeps_legacy_explicit() -> None:
    """Only a valid v2 envelope or a schema-free legacy payload is accepted."""

    router = _load_router()
    payload = router.opencode_payload(_request(router))["client_payload"]
    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    code = _python_heredoc(
        _named_step(workflow, "Validate targeted repository dispatch")
    )
    common = {"EXPECTED_SCHEMA": SCHEMA}

    valid = _run_python_contract(
        code,
        {
            **common,
            "DISPATCH_CLIENT_PAYLOAD_JSON": json.dumps(payload),
            "GITHUB_EVENT_ACTION": "merge-scheduler-agent-review-v2",
        },
    )
    assert valid.returncode == 0, valid.stderr

    legacy = _run_python_contract(
        code,
        {
            **common,
            "DISPATCH_CLIENT_PAYLOAD_JSON": json.dumps(
                {"target_repository": "ContextualWisdomLab/example", "pr_number": 17}
            ),
            "GITHUB_EVENT_ACTION": "merge-scheduler",
        },
    )
    assert legacy.returncode == 0, legacy.stderr

    wrong_event = _run_python_contract(
        code,
        {
            **common,
            "DISPATCH_CLIENT_PAYLOAD_JSON": json.dumps(payload),
            "GITHUB_EVENT_ACTION": "merge-scheduler",
        },
    )
    assert wrong_event.returncode != 0

    malformed = deepcopy(payload)
    malformed["claim"]["update_branches"] = True
    invalid_policy = _run_python_contract(
        code,
        {
            **common,
            "DISPATCH_CLIENT_PAYLOAD_JSON": json.dumps(malformed),
            "GITHUB_EVENT_ACTION": "merge-scheduler-agent-review-v2",
        },
    )
    assert invalid_policy.returncode != 0


def test_agent_mention_quality_gate_covers_the_downstream_scheduler_contract() -> None:
    """Every production and regression path in this transport runs its quality gate."""

    workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")

    for path in (
        '.github/workflows/pr-review-merge-scheduler.yml',
        'scripts/ci/pr_review_merge_scheduler.py',
        'scripts/ci/pr_review_fix_scheduler.py',
        'tests/test_pr_review_merge_scheduler.py',
    ):
        assert workflow.count(f'      - "{path}"') == 2

    coverage_config = workflow.split("[run]\n", 1)[1].split("[report]\n", 1)[0]
    assert "scripts/ci/pr_review_merge_scheduler.py" in coverage_config
    interrogate = workflow.split("python -m interrogate --fail-under=100", 1)[1].split(
        "python -m compileall", 1
    )[0]
    assert "scripts/ci/pr_review_merge_scheduler.py" in interrogate
