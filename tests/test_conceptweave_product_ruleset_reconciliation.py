from __future__ import annotations

import base64
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import (
    AmbiguousRulesetWriteError,
    RulesetGovernanceError,
)


def manifest(ruleset_id=None, blob_sha="f" * 40):
    return {
        "schema_version": 1,
        "target_repository": p.TARGET_FULL_NAME,
        "target_branch": p.TARGET_BRANCH,
        "ruleset_name": p.RULESET_NAME,
        "ruleset_id": ruleset_id,
        "required_check": p.PRODUCT_CHECK,
        "forbidden_check": p.METADATA_ONLY_CHECK,
        "product_workflow_blob_sha": blob_sha,
    }


def write_manifest(tmp_path: Path, data):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def live_payload(ruleset_id=99, *, enforcement="evaluate"):
    return {
        "id": ruleset_id,
        "source_type": "Organization",
        "source": p.ORGANIZATION,
        **p._desired(enforcement=enforcement),
    }


def completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def workflow_payload(text=None):
    if text is None:
        text = "name: Product\nx: 'Product acceptance'\ny: 'Product metadata-only'\nconcurrency:\n  cancel-in-progress: false\n"
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(),
    }


def test_manifest_valid_and_invalid(tmp_path):
    assert p.load_product_manifest(write_manifest(tmp_path, manifest())) == manifest()
    mutations = [
        lambda d: d.update(extra=True),
        lambda d: d.__setitem__("schema_version", 2),
        lambda d: d.__setitem__("target_repository", "x/y"),
        lambda d: d.__setitem__("target_branch", "dev"),
        lambda d: d.__setitem__("ruleset_name", "x"),
        lambda d: d.__setitem__("required_check", "x"),
        lambda d: d.__setitem__("forbidden_check", "x"),
        lambda d: d.__setitem__("ruleset_id", 0),
        lambda d: d.__setitem__("ruleset_id", True),
    ]
    for mutate in mutations:
        data = manifest()
        mutate(data)
        with pytest.raises(RulesetGovernanceError):
            p.load_product_manifest(write_manifest(tmp_path, data))


def test_target_and_desired():
    target = p._target(7)
    assert target.scope == "organization"
    assert target.repository is None
    assert target.endpoint.endswith("/7")
    with pytest.raises(RulesetGovernanceError):
        p._target(0)
    desired = p._desired(enforcement="evaluate")
    assert desired["target"] == "branch"
    assert desired["conditions"]["repository_id"]["repository_ids"] == [p.TARGET_REPOSITORY_ID]
    assert desired["rules"][0]["type"] == "workflows"
    assert desired["rules"][0]["parameters"]["workflows"][0] == {
        "repository_id": p.TARGET_REPOSITORY_ID,
        "path": p.PRODUCT_WORKFLOW_PATH,
        "ref": "refs/heads/main",
    }
    with pytest.raises(RulesetGovernanceError):
        p._desired(enforcement="bad")


def test_assert_shape(monkeypatch):
    target = p._target(9)
    monkeypatch.setattr(p, "_assert_target_provenance", lambda live, target: None)
    p._assert_shape(live_payload(9), target, enforcement="evaluate")
    bad = live_payload(9)
    bad["name"] = "bad"
    with pytest.raises(RulesetGovernanceError, match="name"):
        p._assert_shape(bad, target, enforcement="evaluate")
    bad = live_payload(9)
    bad["bypass_actors"] = [{"actor_id": 1}]
    with pytest.raises(RulesetGovernanceError, match="reviewed"):
        p._assert_shape(bad, target, enforcement="evaluate")


def test_organization_rulesets_and_named(monkeypatch):
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"id": 1, "name": "other", "source_type": "Organization", "source": p.ORGANIZATION},
        {"id": 2, "name": p.RULESET_NAME, "source_type": "Organization", "source": p.ORGANIZATION},
    ])
    assert p._named_ruleset()["id"] == 2
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"id": 1, "name": p.RULESET_NAME, "source_type": "Repository", "source": p.TARGET_FULL_NAME}
    ])
    with pytest.raises(RulesetGovernanceError, match="foreign"):
        p._organization_rulesets()
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"id": 1, "name": p.RULESET_NAME, "source_type": "Organization", "source": p.ORGANIZATION},
        {"id": 2, "name": p.RULESET_NAME, "source_type": "Organization", "source": p.ORGANIZATION},
    ])
    with pytest.raises(RulesetGovernanceError, match="multiple"):
        p._named_ruleset()


def test_live(monkeypatch):
    target = p._target(4)
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: live_payload(4))
    monkeypatch.setattr(p, "_assert_target_provenance", lambda live, target: None)
    assert p._live(target)["id"] == 4


def test_verify_absent_and_states(monkeypatch):
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    assert p.verify_product_ruleset(manifest()) == "absent"
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 9})
    with pytest.raises(RulesetGovernanceError, match="pin"):
        p.verify_product_ruleset(manifest())
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="absent"):
        p.verify_product_ruleset(manifest(9))
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 9})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(9))
    monkeypatch.setattr(p, "_assert_shape", lambda *a, **k: None)
    assert p.verify_product_ruleset(manifest(9)) == "evaluate"
    monkeypatch.setattr(p, "_live", lambda t: live_payload(9, enforcement="active"))
    assert p.verify_product_ruleset(manifest(9)) == "active"
    bad = live_payload(9)
    bad["enforcement"] = "disabled"
    monkeypatch.setattr(p, "_live", lambda t: bad)
    with pytest.raises(RulesetGovernanceError, match="unsupported"):
        p.verify_product_ruleset(manifest(9))


def test_create_evaluate_success_and_settlement(monkeypatch):
    created = live_payload(11)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(json.dumps(created)))
    assert p._create_evaluate_ruleset()["id"] == 11

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed("{"))
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 12})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(12))
    monkeypatch.setattr(p, "_assert_shape", lambda *a, **k: None)
    assert p._create_evaluate_ruleset()["id"] == 12

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("gh", 30)
    monkeypatch.setattr(subprocess, "run", timeout)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 13})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(13))
    assert p._create_evaluate_ruleset()["id"] == 13

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed("", 1))
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 14})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(14))
    assert p._create_evaluate_ruleset()["id"] == 14

    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="ambiguous"):
        p._create_evaluate_ruleset()


def test_target_main(monkeypatch):
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {"object": {"sha": "a" * 40}})
    assert p._target_main_sha() == "a" * 40
    p._assert_target_main("a" * 40)
    with pytest.raises(RulesetGovernanceError, match="advanced"):
        p._assert_target_main("b" * 40)
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {"object": {"sha": "bad"}})
    with pytest.raises(RulesetGovernanceError, match="malformed"):
        p._target_main_sha()


def test_bootstrap_paths(monkeypatch):
    checks = []
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: checks.append(sha))
    monkeypatch.setattr(p, "_assert_shape", lambda *a, **k: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 20})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(20))
    assert p.bootstrap_product_ruleset(manifest(20), expected_main_sha="a" * 40) == 20
    assert checks == ["a" * 40, "a" * 40]

    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="absent"):
        p.bootstrap_product_ruleset(manifest(20), expected_main_sha="a" * 40)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 21})
    with pytest.raises(RulesetGovernanceError, match="pin"):
        p.bootstrap_product_ruleset(manifest(), expected_main_sha="a" * 40)


def test_bootstrap_create(monkeypatch):
    seen = []
    target_seen = []
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: seen.append(sha))
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    monkeypatch.setattr(p, "_target_main_sha", lambda: "b" * 40)
    monkeypatch.setattr(p, "_assert_base_product_workflow", lambda sha, **kwargs: None)
    monkeypatch.setattr(p, "_assert_target_main", lambda sha: target_seen.append(sha))
    monkeypatch.setattr(p, "_create_evaluate_ruleset", lambda: live_payload(22))
    monkeypatch.setattr(p, "_assert_shape", lambda *a, **k: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda target: 3)
    monkeypatch.setattr(p, "_history_version_state", lambda target, version: live_payload(22))
    assert p.bootstrap_product_ruleset(manifest(), expected_main_sha="a" * 40) == 22
    assert seen == ["a" * 40, "a" * 40, "a" * 40, "a" * 40]
    assert target_seen == ["b" * 40, "b" * 40, "b" * 40]


def test_decode_and_base_workflow(monkeypatch):
    text = "name: Product\n'Product acceptance'\n'Product metadata-only'\ncancel-in-progress: false\n"
    payload = workflow_payload(text)
    assert p._decode_workflow(payload) == text
    wrapped = dict(payload)
    wrapped["content"] = "\n".join(payload["content"][i:i+10] for i in range(0, len(payload["content"]), 10))
    assert p._decode_workflow(wrapped) == text
    for bad in (
        {"type": "dir", "encoding": "base64", "content": ""},
        {"type": "file", "encoding": "base64", "content": None},
        {"type": "file", "encoding": "base64", "content": "!"},
    ):
        with pytest.raises(RulesetGovernanceError):
            p._decode_workflow(bad)

    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: payload)
    p._assert_base_product_workflow("a" * 40)
    bad = workflow_payload("name: Product\n")
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: bad)
    with pytest.raises(RulesetGovernanceError, match="acceptance"):
        p._assert_base_product_workflow("a" * 40)


def test_parse_timestamp():
    assert p._parse_timestamp("2026-09-23T00:00:00Z", field="x").tzinfo is not None
    with pytest.raises(RulesetGovernanceError, match="missing"):
        p._parse_timestamp(None, field="x")
    with pytest.raises(RulesetGovernanceError, match="malformed"):
        p._parse_timestamp("no", field="x")


def test_latest_base_retarget(monkeypatch):
    timeline = [
        {"event": "base_ref_changed", "created_at": "2026-09-23T00:00:00Z"},
        {"event": "commented", "created_at": "2026-09-23T00:01:00Z"},
    ]
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: timeline)
    assert p._latest_base_retarget(5) == datetime(2026, 9, 23, tzinfo=timezone.utc)

    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [])
    with pytest.raises(RulesetGovernanceError, match="lacks"):
        p._latest_base_retarget(5)

    monkeypatch.setattr(p, "_gh_api_list", lambda *a: timeline + [
        {"event": "committed", "created_at": "2026-09-23T00:02:00Z"}
    ])
    with pytest.raises(RulesetGovernanceError, match="source commit"):
        p._latest_base_retarget(5)


def canary_api(**overrides):
    head_sha = overrides.get("head_sha", "b" * 40)
    base_sha = overrides.get("base_sha", "a" * 40)
    pr_number = overrides.get("pr_number", 5)
    run_id = overrides.get("run_id", 77)
    run = {
        "name": p.PRODUCT_WORKFLOW_NAME,
        "path": p.PRODUCT_WORKFLOW_PATH,
        "event": "pull_request",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "created_at": "2026-09-23T00:01:00Z",
        "pull_requests": [{"number": pr_number, "head": {"sha": head_sha}, "base": {"sha": base_sha}}],
    }
    run.update(overrides.get("run_overrides", {}))
    def api(method, endpoint, **kwargs):
        if endpoint.endswith(f"pulls/{pr_number}"):
            return {
                "state": overrides.get("pr_state", "open"),
                "draft": overrides.get("draft", False),
                "head": {"sha": head_sha},
                "base": {"ref": overrides.get("base_ref", "main"), "sha": base_sha},
            }
        if endpoint.endswith(f"actions/runs/{run_id}"):
            return run
        if f"actions/runs/{run_id}/jobs" in endpoint:
            return {"jobs": overrides.get("jobs", [{"name": p.PRODUCT_CHECK, "status": "completed", "conclusion": "success"}])}
        raise AssertionError(endpoint)
    return api


def setup_canary(monkeypatch, **kwargs):
    monkeypatch.setattr(p, "_gh_api", canary_api(**kwargs))
    monkeypatch.setattr(p, "_assert_target_main", lambda sha: None)
    monkeypatch.setattr(p, "_assert_base_product_workflow", lambda sha, **kwargs: None)
    monkeypatch.setattr(
        p,
        "_latest_base_retarget",
        lambda pr: datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc),
    )


def test_canary_success(monkeypatch):
    setup_canary(monkeypatch)
    assert p._canary_evidence(pr_number=5, run_id=77) == ("a" * 40, "b" * 40)


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"pr_state": "closed"}, "open"),
        ({"draft": True}, "open"),
        ({"head_sha": "bad"}, "malformed"),
        ({"base_ref": "dev"}, "protected main"),
        ({"run_overrides": {"name": "Other"}}, "terminal Product"),
        ({"run_overrides": {"path": ".github/workflows/other.yml"}}, "terminal Product"),
        ({"run_overrides": {"event": "push"}}, "terminal Product"),
        ({"run_overrides": {"status": "queued"}}, "terminal Product"),
        ({"run_overrides": {"conclusion": "failure"}}, "terminal Product"),
        ({"run_overrides": {"run_attempt": 2}}, "terminal Product"),
        ({"run_overrides": {"created_at": "2026-09-22T23:59:00Z"}}, "predates"),
        ({"run_overrides": {"pull_requests": []}}, "bound"),
        ({"jobs": []}, "uniquely successful"),
        ({"jobs": [{"name": p.PRODUCT_CHECK, "status": "completed", "conclusion": "failure"}]}, "uniquely successful"),
    ],
)
def test_canary_rejects(monkeypatch, kwargs, match):
    setup_canary(monkeypatch, **kwargs)
    with pytest.raises(RulesetGovernanceError, match=match):
        p._canary_evidence(pr_number=5, run_id=77)


def test_canary_nonpositive():
    with pytest.raises(RulesetGovernanceError, match="positive"):
        p._canary_evidence(pr_number=0, run_id=1)


def test_evaluate_rule_suite(monkeypatch):
    base, head = "a" * 40, "b" * 40
    not_before = datetime(2026, 9, 23, tzinfo=timezone.utc)
    suite = {
        "id": 55,
        "repository_id": p.TARGET_REPOSITORY_ID,
        "ref": "refs/heads/main",
        "before_sha": base,
        "after_sha": head,
        "pushed_at": "2026-09-23T00:01:00Z",
    }
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [suite])
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {
        "rule_evaluations": [{
            "rule_source": {"id": 30},
            "enforcement": "evaluate",
            "rule_type": "workflows",
            "result": "pass",
        }]
    })
    p._assert_evaluate_rule_suite(ruleset_id=30, base_sha=base, head_sha=head, not_before=not_before)

    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [])
    with pytest.raises(RulesetGovernanceError, match="one exact"):
        p._assert_evaluate_rule_suite(ruleset_id=30, base_sha=base, head_sha=head, not_before=not_before)

    bad_id = dict(suite, id=0)
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [bad_id])
    with pytest.raises(RulesetGovernanceError, match="identity"):
        p._assert_evaluate_rule_suite(ruleset_id=30, base_sha=base, head_sha=head, not_before=not_before)

    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [suite])
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {"rule_evaluations": []})
    with pytest.raises(RulesetGovernanceError, match="PASS"):
        p._assert_evaluate_rule_suite(ruleset_id=30, base_sha=base, head_sha=head, not_before=not_before)


def setup_activate(monkeypatch, *, ruleset_id=30, active=False):
    before = live_payload(ruleset_id, enforcement="active" if active else "evaluate")
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    monkeypatch.setattr(p, "_assert_target_main", lambda sha: None)
    monkeypatch.setattr(p, "_assert_base_product_workflow", lambda sha, **kwargs: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": ruleset_id})
    monkeypatch.setattr(p, "_live", lambda target: before)
    monkeypatch.setattr(p, "_assert_shape", lambda *a, **k: None)
    monkeypatch.setattr(
        p,
        "_latest_base_retarget",
        lambda pr: datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(p, "_canary_evidence", lambda **k: ("a" * 40, "b" * 40))
    monkeypatch.setattr(p, "_assert_evaluate_rule_suite", lambda **k: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda target: 4)
    return before


def test_activate_success(monkeypatch):
    before = setup_activate(monkeypatch)
    after = live_payload(30, enforcement="active")
    reads = iter([before, before, after])
    monkeypatch.setattr(p, "_live", lambda target: next(reads))
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {})
    verified = []
    monkeypatch.setattr(p, "_verify_ruleset_history_transition", lambda *a, **k: verified.append(1))
    assert p.activate_product_ruleset(manifest(30), expected_main_sha="d"*40, canary_pr=5, canary_run_id=77) == "active"
    assert verified == [1]


def test_activate_ambiguous_success(monkeypatch):
    before = setup_activate(monkeypatch, ruleset_id=31)
    monkeypatch.setattr(p, "_live", lambda target: before)
    def api(*a, **k):
        raise AmbiguousRulesetWriteError("x")
    monkeypatch.setattr(p, "_gh_api", api)
    monkeypatch.setattr(p, "_confirm_ambiguous_put", lambda *a, **k: live_payload(31, enforcement="active"))
    assert p.activate_product_ruleset(manifest(31), expected_main_sha="d"*40, canary_pr=5, canary_run_id=77) == "active"


def test_activate_rejects(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    with pytest.raises(RulesetGovernanceError, match="adoption"):
        p.activate_product_ruleset(manifest(), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)

    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="absent"):
        p.activate_product_ruleset(manifest(32), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)

    setup_activate(monkeypatch, ruleset_id=32, active=True)
    with pytest.raises(RulesetGovernanceError, match="already active"):
        p.activate_product_ruleset(manifest(32), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)

    before = setup_activate(monkeypatch, ruleset_id=33)
    changed = dict(before)
    changed["bypass_actors"] = [{"actor_id": 1}]
    reads = iter([before, changed])
    monkeypatch.setattr(p, "_live", lambda target: next(reads))
    with pytest.raises(RulesetGovernanceError, match="concurrently"):
        p.activate_product_ruleset(manifest(33), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)


def test_positive_int_and_parse_args():
    assert p._positive_int("2") == 2
    with pytest.raises(Exception):
        p._positive_int("0")
    assert p._parse_args(["--mode", "validate"]).mode == "validate"


def test_main_modes(monkeypatch, tmp_path, capsys):
    path = write_manifest(tmp_path, manifest())
    assert p.main(["--manifest", str(path), "--mode", "validate"]) == 0
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RulesetGovernanceError, match="GH_TOKEN"):
        p.main(["--manifest", str(path), "--mode", "verify"])
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(p, "verify_product_ruleset", lambda m: "absent")
    assert p.main(["--manifest", str(path), "--mode", "verify"]) == 0
    monkeypatch.delenv("CWL_RULESET_RECONCILE_ENABLED", raising=False)
    with pytest.raises(RulesetGovernanceError, match="disabled"):
        p.main(["--manifest", str(path), "--mode", "bootstrap", "--expected-main-sha", "a"*40])
    monkeypatch.setenv("CWL_RULESET_RECONCILE_ENABLED", "true")
    with pytest.raises(RulesetGovernanceError, match="expected"):
        p.main(["--manifest", str(path), "--mode", "bootstrap"])
    monkeypatch.setattr(p, "bootstrap_product_ruleset", lambda *a, **k: 44)
    assert p.main(["--manifest", str(path), "--mode", "bootstrap", "--expected-main-sha", "a"*40]) == 0
    with pytest.raises(RulesetGovernanceError, match="canary"):
        p.main(["--manifest", str(path), "--mode", "activate", "--expected-main-sha", "a"*40])

    pinned = write_manifest(tmp_path, manifest(44))
    monkeypatch.setattr(p, "activate_product_ruleset", lambda *a, **k: "active")
    assert p.main([
        "--manifest", str(pinned), "--mode", "activate", "--expected-main-sha", "a"*40,
        "--canary-pr", "5", "--canary-run-id", "77",
    ]) == 0
    assert "stage=active" in capsys.readouterr().out


def test_cli_success_and_error(monkeypatch, capsys):
    monkeypatch.setattr(p, "main", lambda: 0)
    with pytest.raises(SystemExit) as exc:
        p.cli()
    assert exc.value.code == 0
    monkeypatch.setattr(p, "main", lambda: (_ for _ in ()).throw(RulesetGovernanceError("boom")))
    with pytest.raises(SystemExit) as exc:
        p.cli()
    assert exc.value.code == 1
    assert "boom" in capsys.readouterr().err


def test_main_bootstrap_pinned_skips_adoption_message(monkeypatch, tmp_path, capsys):
    path = write_manifest(tmp_path, manifest(45))
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("CWL_RULESET_RECONCILE_ENABLED", "true")
    monkeypatch.setattr(p, "bootstrap_product_ruleset", lambda *a, **k: 45)
    assert p.main(["--manifest", str(path), "--mode", "bootstrap", "--expected-main-sha", "a"*40]) == 0
    assert "adoption required" not in capsys.readouterr().out


def test_bootstrap_rejects_unsupported_pinned_stage(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 20})
    bad = live_payload(20)
    bad["enforcement"] = "disabled"
    monkeypatch.setattr(p, "_live", lambda t: bad)
    with pytest.raises(RulesetGovernanceError, match="unsupported"):
        p.bootstrap_product_ruleset(manifest(20), expected_main_sha="a"*40)


def test_latest_base_retarget_ignores_earlier_commit(monkeypatch):
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"event": "committed", "created_at": "2026-09-22T23:59:00Z"},
        {"event": "base_ref_changed", "created_at": "2026-09-23T00:00:00Z"},
    ])
    assert p._latest_base_retarget(5) == datetime(2026, 9, 23, tzinfo=timezone.utc)


def test_evaluate_rule_suite_skips_unrelated_suite_and_evaluation(monkeypatch):
    base, head = "a"*40, "b"*40
    not_before = datetime(2026, 9, 23, tzinfo=timezone.utc)
    unrelated = {
        "id": 54, "repository_id": 999, "ref": "refs/heads/main",
        "before_sha": base, "after_sha": head, "pushed_at": "2026-09-23T00:01:00Z",
    }
    matching = {
        "id": 55, "repository_id": p.TARGET_REPOSITORY_ID, "ref": "refs/heads/main",
        "before_sha": base, "after_sha": head, "pushed_at": "2026-09-23T00:01:00Z",
    }
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [unrelated, matching])
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {
        "rule_evaluations": [
            {"rule_source": {"id": 999}, "enforcement": "evaluate", "rule_type": "workflows", "result": "pass"},
            {"rule_source": {"id": 30}, "enforcement": "evaluate", "rule_type": "workflows", "result": "pass"},
        ]
    })
    p._assert_evaluate_rule_suite(
        ruleset_id=30, base_sha=base, head_sha=head, not_before=not_before
    )
