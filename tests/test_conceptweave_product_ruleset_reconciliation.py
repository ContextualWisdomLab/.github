from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import (
    AmbiguousRulesetWriteError,
    RulesetGovernanceError,
)


def manifest(ruleset_id=None):
    return {
        "schema_version": 1,
        "target_repository": p.TARGET_FULL_NAME,
        "target_branch": p.TARGET_BRANCH,
        "ruleset_name": p.RULESET_NAME,
        "ruleset_id": ruleset_id,
        "required_check": p.PRODUCT_CHECK,
        "forbidden_check": p.METADATA_ONLY_CHECK,
    }


def write_manifest(tmp_path: Path, data):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def live_payload(ruleset_id=99, *, enforcement="evaluate", integration_id=None):
    payload = p._desired(enforcement=enforcement, integration_id=integration_id)
    return {
        "id": ruleset_id,
        "source_type": "Repository",
        "source": p.TARGET_FULL_NAME,
        **payload,
    }


def test_manifest_valid(tmp_path):
    assert p.load_product_manifest(write_manifest(tmp_path, manifest())) == manifest()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=True),
        lambda d: d.__setitem__("schema_version", 2),
        lambda d: d.__setitem__("target_repository", "x/y"),
        lambda d: d.__setitem__("target_branch", "dev"),
        lambda d: d.__setitem__("ruleset_name", "x"),
        lambda d: d.__setitem__("required_check", "x"),
        lambda d: d.__setitem__("forbidden_check", "x"),
        lambda d: d.__setitem__("ruleset_id", 0),
        lambda d: d.__setitem__("ruleset_id", True),
    ],
)
def test_manifest_rejects_invalid(tmp_path, mutate):
    data = manifest()
    mutate(data)
    with pytest.raises(RulesetGovernanceError):
        p.load_product_manifest(write_manifest(tmp_path, data))


def test_target_and_desired_validation():
    assert p._target(7).ruleset_id == 7
    with pytest.raises(RulesetGovernanceError):
        p._target(0)
    assert p._desired(enforcement="evaluate", integration_id=None)["enforcement"] == "evaluate"
    assert p._desired(enforcement="active", integration_id=15368)["rules"][0]["parameters"]["required_status_checks"][0]["integration_id"] == 15368
    with pytest.raises(RulesetGovernanceError):
        p._desired(enforcement="bad", integration_id=None)
    with pytest.raises(RulesetGovernanceError):
        p._desired(enforcement="active", integration_id=0)


def test_assert_shape(monkeypatch):
    target = p._target(9)
    monkeypatch.setattr(p, "_assert_target_provenance", lambda live, target: None)
    p._assert_shape(live_payload(9), target, enforcement="evaluate", integration_id=None)
    bad = live_payload(9)
    bad["name"] = "bad"
    with pytest.raises(RulesetGovernanceError, match="name"):
        p._assert_shape(bad, target, enforcement="evaluate", integration_id=None)
    bad = live_payload(9)
    bad["bypass_actors"] = [{"actor_id": 1}]
    with pytest.raises(RulesetGovernanceError, match="reviewed"):
        p._assert_shape(bad, target, enforcement="evaluate", integration_id=None)


def test_repository_rulesets_and_named(monkeypatch):
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"id": 1, "name": "other", "source_type": "Repository", "source": p.TARGET_FULL_NAME},
        {"id": 2, "name": p.RULESET_NAME, "source_type": "Repository", "source": p.TARGET_FULL_NAME},
    ])
    assert p._named_ruleset()["id"] == 2
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"id": 1, "name": p.RULESET_NAME, "source_type": "Organization", "source": p.ORGANIZATION}
    ])
    with pytest.raises(RulesetGovernanceError, match="foreign"):
        p._repository_rulesets()
    monkeypatch.setattr(p, "_gh_api_list", lambda *a: [
        {"id": 1, "name": p.RULESET_NAME, "source_type": "Repository", "source": p.TARGET_FULL_NAME},
        {"id": 2, "name": p.RULESET_NAME, "source_type": "Repository", "source": p.TARGET_FULL_NAME},
    ])
    with pytest.raises(RulesetGovernanceError, match="multiple"):
        p._named_ruleset()


def test_live(monkeypatch):
    target = p._target(4)
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {"id": 4})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda live, target: None)
    assert p._live(target)["id"] == 4


@pytest.mark.parametrize("rules", [[], [{}, {}]])
def test_active_integration_rejects_rule_count(rules):
    with pytest.raises(RulesetGovernanceError, match="one rule"):
        p._active_integration_id({"rules": rules})


@pytest.mark.parametrize("checks", [[], [{}, {}]])
def test_active_integration_rejects_check_count(checks):
    live = {"rules": [{"parameters": {"required_status_checks": checks}}]}
    with pytest.raises(RulesetGovernanceError, match="one check"):
        p._active_integration_id(live)


def test_active_integration_id():
    live = {"rules": [{"parameters": {"required_status_checks": [{"integration_id": 15368}]}}]}
    assert p._active_integration_id(live) == 15368
    live["rules"][0]["parameters"]["required_status_checks"][0]["integration_id"] = None
    with pytest.raises(RulesetGovernanceError, match="positive"):
        p._active_integration_id(live)


def test_verify_absent_and_unpinned_existing(monkeypatch):
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    assert p.verify_product_ruleset(manifest()) == "absent"
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 9})
    with pytest.raises(RulesetGovernanceError, match="pin"):
        p.verify_product_ruleset(manifest())


def test_verify_pinned_missing(monkeypatch):
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="absent"):
        p.verify_product_ruleset(manifest(9))


def test_verify_evaluate_active_and_unknown(monkeypatch):
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 9})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    monkeypatch.setattr(p, "_live", lambda t: live_payload(9))
    assert p.verify_product_ruleset(manifest(9)) == "evaluate"
    monkeypatch.setattr(p, "_live", lambda t: live_payload(9, enforcement="active", integration_id=15368))
    assert p.verify_product_ruleset(manifest(9)) == "active"
    bad = live_payload(9)
    bad["enforcement"] = "disabled"
    monkeypatch.setattr(p, "_live", lambda t: bad)
    with pytest.raises(RulesetGovernanceError, match="unsupported"):
        p.verify_product_ruleset(manifest(9))


def completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_create_evaluate_success(monkeypatch):
    created = live_payload(11)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed(json.dumps(created)))
    assert p._create_evaluate_ruleset()["id"] == 11


def test_create_evaluate_success_invalid_json_settles(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed("{"))
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 12})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(12))
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    assert p._create_evaluate_ruleset()["id"] == 12


@pytest.mark.parametrize("outcome", ["timeout", "nonzero"])
def test_create_evaluate_ambiguous_settles(monkeypatch, outcome):
    def run(*a, **k):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("gh", 30)
        return completed("", 1)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 13})
    monkeypatch.setattr(p, "_live", lambda t: live_payload(13))
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    assert p._create_evaluate_ruleset()["id"] == 13


def test_create_evaluate_ambiguous_without_live_identity(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed("", 1))
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="ambiguous"):
        p._create_evaluate_ruleset()


def test_bootstrap_pinned_evaluate_and_active(monkeypatch):
    calls = []
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: calls.append(sha))
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 20})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    monkeypatch.setattr(p, "_live", lambda t: live_payload(20))
    assert p.bootstrap_product_ruleset(manifest(20), expected_main_sha="a"*40) == 20
    monkeypatch.setattr(p, "_live", lambda t: live_payload(20, enforcement="active", integration_id=15368))
    assert p.bootstrap_product_ruleset(manifest(20), expected_main_sha="a"*40) == 20
    assert len(calls) == 4


def test_bootstrap_pinned_missing(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="absent"):
        p.bootstrap_product_ruleset(manifest(20), expected_main_sha="a"*40)


def test_bootstrap_unpinned_existing(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 21})
    with pytest.raises(RulesetGovernanceError, match="pin"):
        p.bootstrap_product_ruleset(manifest(), expected_main_sha="a"*40)


def test_bootstrap_creates_and_verifies_history(monkeypatch):
    seen = []
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: seen.append(sha))
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    monkeypatch.setattr(p, "_create_evaluate_ruleset", lambda: live_payload(22))
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda target: 3)
    monkeypatch.setattr(p, "_history_version_state", lambda target, version: live_payload(22))
    assert p.bootstrap_product_ruleset(manifest(), expected_main_sha="a"*40) == 22
    assert seen == ["a"*40, "a"*40]


def test_decode_workflow():
    text = "name: Product"
    payload = {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(),
    }
    assert p._decode_workflow(payload) == text
    with pytest.raises(RulesetGovernanceError, match="base64 file"):
        p._decode_workflow({"type": "dir", "encoding": "base64", "content": ""})
    with pytest.raises(RulesetGovernanceError, match="malformed"):
        p._decode_workflow({"type": "file", "encoding": "base64", "content": None})
    with pytest.raises(RulesetGovernanceError, match="invalid"):
        p._decode_workflow({"type": "file", "encoding": "base64", "content": "!"})


def test_assert_base_product_workflow(monkeypatch):
    good = "name: Product\nx: 'Product acceptance'\ny: 'Product metadata-only'\n"
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(good.encode()).decode(),
    })
    p._assert_base_product_workflow("a"*40)
    bad = "name: Product\n"
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(bad.encode()).decode(),
    })
    with pytest.raises(RulesetGovernanceError, match="identities"):
        p._assert_base_product_workflow("a"*40)


def canary_api(head_sha="b"*40, base_sha="a"*40, run_id=77, pr_number=5, *,
               pr_state="open", draft=False, base_ref="main", run_name="Product",
               run_event="pull_request", run_status="completed", run_conclusion="success",
               job_name="Product acceptance", job_status="completed", job_conclusion="success",
               app_id=15368, bound=True, check_ok=True):
    workflow = "name: Product\nn: 'Product acceptance'\nm: 'Product metadata-only'\n"
    def api(method, endpoint, **kwargs):
        if endpoint.endswith(f"pulls/{pr_number}"):
            return {
                "state": pr_state,
                "draft": draft,
                "head": {"sha": head_sha},
                "base": {"ref": base_ref, "sha": base_sha},
            }
        if endpoint.endswith("git/ref/heads/main"):
            return {"object": {"sha": base_sha}}
        if "contents/.github/workflows/product.yml" in endpoint:
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(workflow.encode()).decode(),
            }
        if endpoint.endswith(f"actions/runs/{run_id}"):
            return {
                "name": run_name,
                "event": run_event,
                "head_sha": head_sha,
                "status": run_status,
                "conclusion": run_conclusion,
                "check_suite_id": 900,
                "pull_requests": [
                    {
                        "number": pr_number if bound else pr_number + 1,
                        "head": {"sha": head_sha},
                        "base": {"sha": base_sha},
                    }
                ],
            }
        if f"actions/runs/{run_id}/jobs" in endpoint:
            return {
                "jobs": [
                    {
                        "name": job_name,
                        "status": job_status,
                        "conclusion": job_conclusion,
                    }
                ]
            }
        if "check-runs" in endpoint:
            return {
                "check_runs": [
                    {
                        "name": p.PRODUCT_CHECK if check_ok else "Other",
                        "check_suite": {"id": 900},
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": app_id},
                    }
                ]
            }
        raise AssertionError(endpoint)
    return api


def test_canary_success(monkeypatch):
    monkeypatch.setattr(p, "_gh_api", canary_api())
    assert p._canary_integration_id(pr_number=5, run_id=77) == 15368


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({}, "positive"),
    ],
)
def test_canary_nonpositive(kwargs, match):
    with pytest.raises(RulesetGovernanceError, match=match):
        p._canary_integration_id(pr_number=0, run_id=1)


@pytest.mark.parametrize(
    "api,match",
    [
        (canary_api(pr_state="closed"), "open"),
        (canary_api(draft=True), "open"),
        (canary_api(head_sha="bad"), "malformed"),
        (canary_api(base_ref="dev"), "protected main"),
        (canary_api(run_name="Other"), "terminal Product"),
        (canary_api(run_event="push"), "terminal Product"),
        (canary_api(run_status="queued"), "terminal Product"),
        (canary_api(run_conclusion="failure"), "terminal Product"),
        (canary_api(bound=False), "bound"),
        (canary_api(job_name="Product metadata-only"), "exactly one"),
        (canary_api(job_status="queued"), "not successful"),
        (canary_api(job_conclusion="failure"), "not successful"),
        (canary_api(check_ok=False), "one exact"),
        (canary_api(app_id=0), "positive integration"),
    ],
)
def test_canary_rejects(monkeypatch, api, match):
    monkeypatch.setattr(p, "_gh_api", api)
    with pytest.raises(RulesetGovernanceError, match=match):
        p._canary_integration_id(pr_number=5, run_id=77)


def test_canary_rejects_stale_base(monkeypatch):
    api = canary_api()
    def stale(method, endpoint, **kwargs):
        if endpoint.endswith("git/ref/heads/main"):
            return {"object": {"sha": "c"*40}}
        return api(method, endpoint, **kwargs)
    monkeypatch.setattr(p, "_gh_api", stale)
    with pytest.raises(RulesetGovernanceError, match="current"):
        p._canary_integration_id(pr_number=5, run_id=77)


def test_activate_success(monkeypatch):
    main_calls = []
    live_calls = {"n": 0}
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: main_calls.append(sha))
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 30})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    before = live_payload(30)
    after = live_payload(30, enforcement="active", integration_id=15368)
    def live(target):
        live_calls["n"] += 1
        return before if live_calls["n"] <= 2 else after
    monkeypatch.setattr(p, "_live", live)
    monkeypatch.setattr(p, "_canary_integration_id", lambda **k: 15368)
    monkeypatch.setattr(p, "_latest_history_version", lambda target: 4)
    monkeypatch.setattr(p, "_gh_api", lambda *a, **k: {})
    verified = []
    monkeypatch.setattr(p, "_verify_ruleset_history_transition", lambda *a, **k: verified.append((a, k)))
    assert p.activate_product_ruleset(
        manifest(30), expected_main_sha="a"*40, canary_pr=5, canary_run_id=77
    ) == 15368
    assert len(main_calls) == 4
    assert verified


def test_activate_ambiguous_success(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 31})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    monkeypatch.setattr(p, "_live", lambda target: live_payload(31))
    monkeypatch.setattr(p, "_canary_integration_id", lambda **k: 15368)
    monkeypatch.setattr(p, "_latest_history_version", lambda target: 4)
    def api(*a, **k):
        raise AmbiguousRulesetWriteError("x")
    monkeypatch.setattr(p, "_gh_api", api)
    after = live_payload(31, enforcement="active", integration_id=15368)
    monkeypatch.setattr(p, "_confirm_ambiguous_put", lambda *a, **k: after)
    assert p.activate_product_ruleset(
        manifest(31), expected_main_sha="a"*40, canary_pr=5, canary_run_id=77
    ) == 15368


def test_activate_requires_pinned(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    with pytest.raises(RulesetGovernanceError, match="adoption"):
        p.activate_product_ruleset(
            manifest(), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1
        )


def test_activate_missing_or_active_or_concurrent(monkeypatch):
    monkeypatch.setattr(p, "_assert_current_main", lambda sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    with pytest.raises(RulesetGovernanceError, match="absent"):
        p.activate_product_ruleset(manifest(32), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": 32})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *a: None)
    monkeypatch.setattr(p, "_live", lambda target: live_payload(32, enforcement="active", integration_id=15368))
    with pytest.raises(RulesetGovernanceError, match="already active"):
        p.activate_product_ruleset(manifest(32), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)

    states = iter([live_payload(32), {**live_payload(32), "bypass_actors": [{"actor_id": 1}]}])
    monkeypatch.setattr(p, "_live", lambda target: next(states))
    monkeypatch.setattr(p, "_canary_integration_id", lambda **k: 15368)
    monkeypatch.setattr(p, "_latest_history_version", lambda target: 1)
    with pytest.raises(RulesetGovernanceError, match="concurrently"):
        p.activate_product_ruleset(manifest(32), expected_main_sha="a"*40, canary_pr=1, canary_run_id=1)


def test_positive_int_and_parse_args():
    assert p._positive_int("2") == 2
    with pytest.raises(Exception):
        p._positive_int("0")
    args = p._parse_args(["--mode", "validate"])
    assert args.mode == "validate"


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
    monkeypatch.setattr(p, "activate_product_ruleset", lambda *a, **k: 15368)
    assert p.main([
        "--manifest", str(pinned), "--mode", "activate", "--expected-main-sha", "a"*40,
        "--canary-pr", "5", "--canary-run-id", "77",
    ]) == 0
    assert "integration_id=15368" in capsys.readouterr().out


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
