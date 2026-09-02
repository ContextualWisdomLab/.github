"""Regression tests for ruleset owner-plane reconciliation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"
SPEC = importlib.util.spec_from_file_location("ruleset_governance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def target(scope: str = "repository"):
    """Build one valid target for unit tests."""

    if scope == "organization":
        return module.RulesetTarget(
            "organization",
            "ContextualWisdomLab",
            None,
            18156473,
            "CWL Central required workflows",
        )
    return module.RulesetTarget(
        "repository",
        "ContextualWisdomLab",
        ".github",
        17921150,
        "Lock default branch",
    )


def live_payload(scope: str = "repository") -> dict[str, object]:
    """Build a realistic live ruleset payload with deliberate governance drift."""

    item = target(scope)
    return {
        "id": item.ruleset_id,
        "name": item.name,
        "target": "branch",
        "source_type": item.source_type,
        "source": item.source,
        "enforcement": "active",
        "bypass_actors": [
            {"actor_id": None, "actor_type": "OrganizationAdmin", "bypass_mode": "always"}
        ],
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 1 if scope == "organization" else 0,
                    "dismiss_stale_reviews_on_push": True,
                    "required_reviewers": [],
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                },
            },
        ],
        "node_id": "server-managed",
    }


def write_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    """Write one manifest payload for validation tests."""

    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_manifest() -> dict[str, object]:
    """Return the reviewed two-target manifest shape."""

    return {
        "schema_version": 1,
        "organization": "ContextualWisdomLab",
        "targets": [
            {
                "scope": "repository",
                "owner": "ContextualWisdomLab",
                "repository": ".github",
                "ruleset_id": 17921150,
                "name": "Lock default branch",
            },
            {
                "scope": "organization",
                "owner": "ContextualWisdomLab",
                "repository": None,
                "ruleset_id": 18156473,
                "name": "CWL Central required workflows",
            },
        ],
    }


def test_target_endpoints_and_identity_properties() -> None:
    """Endpoint/source derivation is exact for both supported ownership scopes."""

    repo = target()
    org = target("organization")
    assert repo.endpoint == "repos/ContextualWisdomLab/.github/rulesets/17921150"
    assert repo.source == "ContextualWisdomLab/.github"
    assert repo.source_type == "Repository"
    assert org.endpoint == "orgs/ContextualWisdomLab/rulesets/18156473"
    assert org.source == "ContextualWisdomLab"
    assert org.source_type == "Organization"


def test_load_manifest_accepts_only_exact_reviewed_shape(tmp_path: Path) -> None:
    """A valid manifest yields exactly one repository and one organization target."""

    targets = module.load_manifest(write_manifest(tmp_path, valid_manifest()))
    assert [item.scope for item in targets] == ["repository", "organization"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update(extra=True), "unexpected key set"),
        (lambda payload: payload.update(schema_version=2), "schema or organization"),
        (lambda payload: payload.update(organization="other"), "schema or organization"),
        (lambda payload: payload.update(targets={}), "targets must be an array"),
        (lambda payload: payload.update(targets=[]), "exactly two"),
        (lambda payload: payload["targets"][0].update(extra=True), "unexpected key set"),
        (lambda payload: payload["targets"][0].update(scope="enterprise"), "scope is unsupported"),
        (lambda payload: payload["targets"][0].update(owner="other"), "identity is invalid"),
        (lambda payload: payload["targets"][0].update(ruleset_id=True), "identity is invalid"),
        (lambda payload: payload["targets"][0].update(ruleset_id=0), "identity is invalid"),
        (lambda payload: payload["targets"][0].update(name=""), "name is invalid"),
        (lambda payload: payload["targets"][1].update(repository="oops"), "repository must be null"),
        (lambda payload: payload["targets"][0].update(repository=None), "must be non-empty"),
        (
            lambda payload: payload["targets"].__setitem__(1, dict(payload["targets"][0])),
            "duplicate ruleset target",
        ),
        (
            lambda payload: payload["targets"].__setitem__(
                1,
                {
                    **payload["targets"][0],
                    "ruleset_id": 999,
                    "name": "Other repo rule",
                },
            ),
            "one target per supported scope",
        ),
    ],
)
def test_load_manifest_rejects_unsafe_shapes(tmp_path: Path, mutator, message: str) -> None:
    """Malformed or ambiguously owned ruleset manifests fail closed."""

    payload = valid_manifest()
    mutator(payload)
    with pytest.raises(module.RulesetGovernanceError, match=message):
        module.load_manifest(write_manifest(tmp_path, payload))


def test_plain_helpers_reject_behavior_bearing_containers() -> None:
    """Only built-in JSON container types cross the trust boundary."""

    class DictSubclass(dict):
        pass

    class ListSubclass(list):
        pass

    with pytest.raises(module.RulesetGovernanceError, match="object"):
        module._plain_dict(DictSubclass(), field="x")
    with pytest.raises(module.RulesetGovernanceError, match="array"):
        module._plain_list(ListSubclass(), field="x")


def test_desired_payload_preserves_unrelated_controls_and_removes_drift() -> None:
    """Only governance fields change while every unrelated live rule survives."""

    live = live_payload("organization")
    desired = module._desired_payload(live, target("organization"))
    assert desired["bypass_actors"] == []
    assert desired["conditions"] == live["conditions"]
    assert desired["rules"][0] == {"type": "deletion"}
    params = desired["rules"][2]["parameters"]
    assert params["required_approving_review_count"] == 0
    assert params["require_code_owner_review"] is False
    assert params["require_last_push_approval"] is False
    assert params["required_reviewers"] == []
    assert params["allowed_merge_methods"] == ["merge", "squash"]
    assert params["dismiss_stale_reviews_on_push"] is True
    assert live["bypass_actors"]
    assert "node_id" not in desired


@pytest.mark.parametrize("field", ["id", "name", "target", "source_type", "source", "enforcement"])
def test_desired_payload_rejects_identity_drift(field: str) -> None:
    """A renamed, re-scoped, disabled, or replaced live ruleset is never overwritten."""

    live = live_payload()
    live[field] = "wrong"
    with pytest.raises(module.RulesetGovernanceError, match="identity drift"):
        module._desired_payload(live, target())


def test_projection_requires_all_editable_fields_and_container_shapes() -> None:
    """Missing or behavior-bearing update fields fail before an API mutation."""

    live = live_payload()
    del live["rules"]
    with pytest.raises(module.RulesetGovernanceError, match="misses editable fields"):
        module._editable_projection(live)
    live = live_payload()
    live["bypass_actors"] = {}
    with pytest.raises(module.RulesetGovernanceError, match="bypass_actors must be an array"):
        module._editable_projection(live)
    live = live_payload()
    live["conditions"] = []
    with pytest.raises(module.RulesetGovernanceError, match="conditions must be an object"):
        module._editable_projection(live)
    live = live_payload()
    live["rules"] = {}
    with pytest.raises(module.RulesetGovernanceError, match="rules must be an array"):
        module._editable_projection(live)


def test_desired_payload_requires_exactly_one_pull_request_rule() -> None:
    """Absent or duplicate pull-request controls cannot be guessed during reconciliation."""

    live = live_payload()
    live["rules"] = [{"type": "deletion"}]
    with pytest.raises(module.RulesetGovernanceError, match="exactly one"):
        module._desired_payload(live, target())
    live = live_payload()
    live["rules"].append(copy_rule := dict(live["rules"][2]))
    assert copy_rule["type"] == "pull_request"
    with pytest.raises(module.RulesetGovernanceError, match="exactly one"):
        module._desired_payload(live, target())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_approving_review_count", True),
        ("require_code_owner_review", 0),
        ("require_last_push_approval", 0),
        ("required_reviewers", {}),
        ("allowed_merge_methods", {}),
    ],
)
def test_desired_payload_rejects_malformed_pull_request_parameters(field: str, value) -> None:
    """Typed GitHub pull-request parameters are validated before modification."""

    live = live_payload()
    live["rules"][2]["parameters"][field] = value
    with pytest.raises(module.RulesetGovernanceError, match=field):
        module._desired_payload(live, target())


def test_desired_payload_rejects_non_object_parameters() -> None:
    """The pull-request parameter object cannot be replaced by another JSON type."""

    live = live_payload()
    live["rules"][2]["parameters"] = []
    with pytest.raises(module.RulesetGovernanceError, match="must be an object"):
        module._desired_payload(live, target())


def test_reconcile_target_skips_already_converged_state(monkeypatch) -> None:
    """An already compliant live ruleset performs no write in either mode."""

    live = live_payload()
    live = {**live, **module._desired_payload(live, target())}
    calls = []

    def fake_api(method, endpoint, *, body=None):
        calls.append((method, endpoint, body))
        return live

    monkeypatch.setattr(module, "_gh_api", fake_api)
    assert module._reconcile_target(target(), verify_only=False) is False
    assert calls == [("GET", target().endpoint, None)]


def test_verify_only_fails_on_drift_without_writing(monkeypatch) -> None:
    """Verification mode reports drift and never sends an update request."""

    calls = []

    def fake_api(method, endpoint, *, body=None):
        calls.append((method, endpoint, body))
        return live_payload()

    monkeypatch.setattr(module, "_gh_api", fake_api)
    with pytest.raises(module.RulesetGovernanceError, match="governance drift remains"):
        module._reconcile_target(target(), verify_only=True)
    assert [item[0] for item in calls] == ["GET"]


def test_apply_rechecks_for_concurrent_drift_before_put(monkeypatch) -> None:
    """A settings race aborts rather than overwriting another administrator's change."""

    first = live_payload()
    second = live_payload()
    second["conditions"] = {"ref_name": {"include": ["refs/heads/reviewed"], "exclude": []}}
    replies = iter([first, second])
    monkeypatch.setattr(module, "_gh_api", lambda *args, **kwargs: next(replies))
    with pytest.raises(module.RulesetGovernanceError, match="changed concurrently"):
        module._reconcile_target(target(), verify_only=False)


def test_apply_mutates_once_and_verifies_exact_convergence(monkeypatch) -> None:
    """A stable target is updated once and post-write live state must equal the reviewed body."""

    first = live_payload()
    desired = module._desired_payload(first, target())
    converged = {**first, **desired}
    calls = []
    replies = iter([first, first, {}, converged])

    def fake_api(method, endpoint, *, body=None):
        calls.append((method, endpoint, body))
        return next(replies)

    monkeypatch.setattr(module, "_gh_api", fake_api)
    assert module._reconcile_target(target(), verify_only=False) is True
    assert [item[0] for item in calls] == ["GET", "GET", "PUT", "GET"]
    assert calls[2][2] == desired


def test_apply_rejects_post_write_nonconvergence(monkeypatch) -> None:
    """A successful HTTP update is not accepted until the full editable payload converges."""

    first = live_payload()
    replies = iter([first, first, {}, first])
    monkeypatch.setattr(module, "_gh_api", lambda *args, **kwargs: next(replies))
    with pytest.raises(module.RulesetGovernanceError, match="did not converge"):
        module._reconcile_target(target(), verify_only=False)


def test_apply_rejects_post_write_identity_replacement(monkeypatch) -> None:
    """A ruleset replacement after PUT fails the exact-identity verification."""

    first = live_payload()
    replaced = live_payload()
    replaced["name"] = "replacement"
    replies = iter([first, first, {}, replaced])
    monkeypatch.setattr(module, "_gh_api", lambda *args, **kwargs: next(replies))
    with pytest.raises(module.RulesetGovernanceError, match="identity drift"):
        module._reconcile_target(target(), verify_only=False)


def test_reconcile_orders_repository_before_organization(monkeypatch) -> None:
    """The strengthening repository mutation precedes the organization approval change."""

    seen = []
    monkeypatch.setattr(
        module,
        "_reconcile_target",
        lambda item, verify_only: seen.append((item.scope, verify_only)) or True,
    )
    targets = (target("organization"), target("repository"))
    assert module.reconcile(targets, verify_only=False) == 2
    assert seen == [("repository", False), ("organization", False)]


def test_gh_api_uses_versioned_stdin_body_and_redacts_failure(monkeypatch) -> None:
    """REST calls pin the API version, send JSON on stdin, and hide subprocess diagnostics."""

    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert module._gh_api("PUT", "endpoint", body={"x": 1}) == {"ok": True}
    assert f"X-GitHub-Api-Version: {module.API_VERSION}" in observed["command"]
    assert observed["input"] == '{"x":1}'
    assert "--input" in observed["command"]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="token-like-output", stderr="secret-like-error"
        ),
    )
    with pytest.raises(module.RulesetGovernanceError, match="GitHub API request failed") as caught:
        module._gh_api("GET", "endpoint")
    assert "secret-like-error" not in str(caught.value)


def test_main_validation_needs_no_token_and_live_modes_do(tmp_path: Path, monkeypatch, capsys) -> None:
    """PR validation is offline; live mutation additionally requires an exact main guard."""

    manifest = write_manifest(tmp_path, valid_manifest())
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert module.main(["--manifest", str(manifest), "--validate-only"]) == 0
    assert "validated 2" in capsys.readouterr().out
    with pytest.raises(module.RulesetGovernanceError, match="GH_TOKEN is required"):
        module.main(["--manifest", str(manifest)])

    monkeypatch.setenv("GH_TOKEN", "not-printed")
    monkeypatch.setattr(
        module,
        "reconcile",
        lambda targets, verify_only, expected_main_sha=None: 0,
    )
    assert module.main(["--manifest", str(manifest), "--verify-only"]) == 0
    assert "verified 2" in capsys.readouterr().out
    with pytest.raises(module.RulesetGovernanceError, match="expected protected main SHA"):
        module.main(["--manifest", str(manifest)])
    assert (
        module.main(
            [
                "--manifest",
                str(manifest),
                "--expected-main-sha",
                "a" * 40,
            ]
        )
        == 0
    )
    assert "reconciled 2" in capsys.readouterr().out


def test_cli_entrypoint_reports_success_and_failure(tmp_path: Path) -> None:
    """The executable entry point maps validation success and unsafe input to exit status."""

    valid = write_manifest(tmp_path, valid_manifest())
    success = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(valid), "--validate-only"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert success.returncode == 0
    assert "validated 2" in success.stdout

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    failure = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(invalid), "--validate-only"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failure.returncode == 1
    assert "ruleset governance reconciliation failed" in failure.stderr


def test_cli_function_maps_main_result_and_expected_failures(monkeypatch, capsys) -> None:
    """The testable CLI boundary exits cleanly and redacts expected failures."""

    monkeypatch.setattr(module, "main", lambda: 0)
    with pytest.raises(SystemExit) as success:
        module.cli()
    assert success.value.code == 0

    def fail():
        raise module.RulesetGovernanceError("unsafe")

    monkeypatch.setattr(module, "main", fail)
    with pytest.raises(SystemExit) as failure:
        module.cli()
    assert failure.value.code == 1
    assert "ruleset governance reconciliation failed: unsafe" in capsys.readouterr().err


def test_workflow_separates_unprivileged_validation_from_owner_plane_apply() -> None:
    """Only trusted main plus an explicit enable flag can enter the privileged environment."""

    workflow = (ROOT / ".github" / "workflows" / "ruleset-governance-reconcile.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in workflow
    assert "schedule:" in workflow
    assert 'github.ref == \'refs/heads/main\'' in workflow
    assert "vars.CWL_RULESET_RECONCILE_ENABLED == 'true'" in workflow
    assert "environment: ruleset-governance-maintenance" in workflow
    assert "secrets.CWL_RULESET_ADMIN_TOKEN" in workflow
    assert "--validate-only" in workflow
    assert "--verify-only" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
