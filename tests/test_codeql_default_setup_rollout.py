import json
from io import StringIO

from scripts.ci import audit_codeql_default_setup_rollout as rollout

HEAD = "a" * 40


def snapshot(**changes):
    value = {
        "name": "xtrmLLMBatchPython",
        "ruleset_applies": True,
        "central_codeql_required": True,
        "expected_head": HEAD,
        "central_codeql_head": HEAD,
        "central_codeql_status": "success",
        "default_setup_state": "not-configured",
        "active_advanced_upload": False,
    }
    value.update(changes)
    return value


def test_pilot_is_verified_only_after_exact_head_central_success():
    assert rollout.classify(snapshot()) == (
        "VERIFIED",
        "default setup is off and exact-head central CodeQL passed",
    )
    assert rollout.classify(snapshot(central_codeql_status="queued"))[0] == "WAIT"
    assert rollout.classify(snapshot(central_codeql_head="b" * 40))[0] == "BLOCK"


def test_default_setup_stays_on_until_central_success():
    assert (
        rollout.classify(
            snapshot(default_setup_state="configured", central_codeql_status="queued")
        )[0]
        == "WAIT"
    )
    assert rollout.classify(snapshot(default_setup_state="configured"))[0] == "READY_DISABLE"


def test_default_setup_and_advanced_uploader_conflict_fails_closed():
    result = rollout.classify(
        snapshot(default_setup_state="configured", active_advanced_upload=True)
    )
    assert result[0] == "BLOCK"
    assert "conflicts" in result[1]


def test_rollback_is_blocked_when_it_would_conflict_with_advanced_upload():
    result = rollout.classify(
        snapshot(central_codeql_status="failure", active_advanced_upload=True)
    )
    assert result[0] == "BLOCK"
    assert "cannot coexist" in result[1]


def test_ruleset_and_documented_exceptions_are_enforced():
    assert rollout.classify(snapshot(ruleset_applies=False))[0] == "BLOCK"
    for name in rollout.EXEMPT_REPOSITORIES:
        assert rollout.classify(snapshot(name=name, ruleset_applies=False))[0] == "EXEMPT"
        assert rollout.classify(snapshot(name=name, ruleset_applies=True))[0] == "BLOCK"


def test_cli_returns_nonzero_for_wait_and_zero_for_verified(capsys, monkeypatch):
    monkeypatch.setattr(rollout.sys, "stdin", StringIO(json.dumps([snapshot()])))
    assert rollout.main([]) == 0
    monkeypatch.setattr(
        rollout.sys,
        "stdin",
        StringIO(json.dumps([snapshot(central_codeql_status="queued")])),
    )
    assert rollout.main([]) == 1
    assert "state=WAIT" in capsys.readouterr().out
