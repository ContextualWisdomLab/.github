from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts" / "ci"))

import agent_source_fix_router as router  # noqa: E402


HEAD = "a" * 40
BASE = "b" * 40


def event(body: str = "@cwl-source-fix repair this PR") -> dict[str, Any]:
    return {
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "issue": {"number": 42, "pull_request": {"url": "https://api.github.com/pr/42"}},
        "comment": {
            "id": 7001,
            "body": body,
            "author_association": "OWNER",
            "user": {"login": "seonghobae", "type": "User"},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": HEAD, "ref": "fix/current-pr"},
            "base": {"sha": BASE, "ref": "main"},
        },
    }


class FakeClient:
    def __init__(self, responses: list[Any] | None = None, failures: set[int] | None = None):
        self.responses = list(responses or [])
        self.failures = set(failures or set())
        self.calls: list[tuple[list[str], Any]] = []

    def request(self, args: list[str], input_payload: Any = None) -> Any:
        index = len(self.calls)
        self.calls.append((list(args), input_payload))
        if index in self.failures:
            raise RuntimeError(f"failure-{index}")
        if self.responses:
            return self.responses.pop(0)
        return {}


def request() -> router.SourceFixRequest:
    parsed = router.parse_event(event())
    assert parsed is not None
    return parsed


def test_receipt_ids_only_accept_actions_bot_markers() -> None:
    comments = [
        {"user": {"login": "someone", "type": "Bot"}, "body": "<!-- cwl-source-fix-receipt:1 -->"},
        {"user": {"login": "github-actions[bot]", "type": "User"}, "body": "<!-- cwl-source-fix-receipt:2 -->"},
        {
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "body": "x <!-- cwl-source-fix-receipt:3 --> y <!-- cwl-source-fix-receipt:4 -->",
        },
    ]
    assert router._receipt_ids(comments) == frozenset({3, 4})


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda e: e["issue"].pop("pull_request"), None),
        (lambda e: e["pull_request"].update(state="closed"), None),
        (lambda e: e["comment"]["user"].update(type="Bot"), None),
        (lambda e: e["comment"].update(author_association="NONE"), None),
        (lambda e: e["comment"].update(body="nothing to do"), None),
    ],
)
def test_parse_event_ignores_non_commands(mutator, expected) -> None:
    value = event()
    mutator(value)
    assert router.parse_event(value) is expected


def test_parse_event_ignores_already_acknowledged_command() -> None:
    value = event()
    value["conversation_comments"] = [
        {
            "user": {"login": "github-actions[bot]", "type": "Bot"},
            "body": "<!-- cwl-source-fix-receipt:7001 -->",
        }
    ]
    assert router.parse_event(value) is None


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda e: e["repository"].update(full_name="outside/repo"), "limited"),
        (lambda e: e["issue"].update(number=0), "number"),
        (lambda e: e["comment"].update(id=0), "comment id"),
        (lambda e: e["pull_request"]["head"].update(sha="bad"), "SHA"),
        (lambda e: e["pull_request"]["base"].update(sha="bad"), "SHA"),
        (lambda e: e["pull_request"]["head"].update(ref="-bad"), "ref"),
        (lambda e: e["pull_request"]["base"].update(ref="-bad"), "ref"),
        (lambda e: e["comment"]["user"].update(login="bad user"), "actor"),
    ],
)
def test_parse_event_rejects_invalid_claim_fields(mutator, message: str) -> None:
    value = event()
    mutator(value)
    with pytest.raises(ValueError, match=message):
        router.parse_event(value)


def test_ledger_name_is_stable_and_prefixed() -> None:
    value = request()
    assert router.ledger_name(value) == router.LEDGER_PREFIX + router.invocation_key(value)
    assert len(router.invocation_key(value)) == 64


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ([], "object"),
        ({"total_count": "1", "artifacts": []}, "malformed"),
        ({"total_count": 1, "artifacts": {}}, "malformed"),
        ({"total_count": 2, "artifacts": []}, "truncated"),
        ({"total_count": 1, "artifacts": ["bad"]}, "non-object"),
        ({"total_count": 1, "artifacts": [{"name": "wrong", "expired": False}]}, "mismatched"),
        ({"total_count": 1, "artifacts": [{"name": "placeholder", "expired": "no"}]}, "mismatched"),
    ],
)
def test_already_claimed_rejects_malformed_artifact_evidence(response, message: str) -> None:
    value = request()
    if isinstance(response, dict) and response.get("artifacts") and isinstance(response["artifacts"][0], dict):
        if response["artifacts"][0].get("name") == "placeholder":
            response["artifacts"][0]["name"] = router.ledger_name(value)
    with pytest.raises(ValueError, match=message):
        router._already_claimed(value, FakeClient([response]))


def test_already_claimed_distinguishes_live_and_expired_artifacts() -> None:
    value = request()
    name = router.ledger_name(value)
    assert not router._already_claimed(value, FakeClient([{"total_count": 0, "artifacts": []}]))
    assert not router._already_claimed(
        value,
        FakeClient([{"total_count": 1, "artifacts": [{"name": name, "expired": True}]}]),
    )
    assert router._already_claimed(
        value,
        FakeClient([{"total_count": 1, "artifacts": [{"name": name, "expired": False}]}]),
    )


def test_dispatch_rejects_unallowlisted_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert not router.dispatch_request(
        request(),
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        repository_allowlist=frozenset(),
    )
    assert "Rejected" in capsys.readouterr().out


def test_dispatch_dry_run_does_not_call_clients(capsys: pytest.CaptureFixture[str]) -> None:
    target = FakeClient()
    dispatch = FakeClient()
    assert router.dispatch_request(
        request(),
        target_client=target,
        dispatch_client=dispatch,
        repository_allowlist=frozenset({"ContextualWisdomLab/.github"}),
        dry_run=True,
    )
    assert not target.calls and not dispatch.calls
    assert "DRY-RUN" in capsys.readouterr().out


def test_dispatch_skips_exact_live_claim() -> None:
    value = request()
    name = router.ledger_name(value)
    dispatch = FakeClient([{"total_count": 1, "artifacts": [{"name": name, "expired": False}]}])
    target = FakeClient()
    assert not router.dispatch_request(
        value,
        target_client=target,
        dispatch_client=dispatch,
        repository_allowlist=frozenset({value.repository}),
    )
    assert not target.calls


def test_dispatch_posts_event_reaction_and_receipt() -> None:
    value = request()
    dispatch = FakeClient([{"total_count": 0, "artifacts": []}, {}])
    target = FakeClient([{}, {}])
    assert router.dispatch_request(
        value,
        target_client=target,
        dispatch_client=dispatch,
        repository_allowlist=frozenset({value.repository.lower()}),
    )
    assert dispatch.calls[1][1] == router.dispatch_payload(value)
    assert target.calls[0][1] == {"content": "eyes"}
    assert f"cwl-source-fix-receipt:{value.comment_id}" in target.calls[1][1]["body"]


@pytest.mark.parametrize("failures", [{0}, {1}])
def test_dispatch_acknowledgement_failures_are_cosmetic(failures, capsys: pytest.CaptureFixture[str]) -> None:
    value = request()
    dispatch = FakeClient([{"total_count": 0, "artifacts": []}, {}])
    target = FakeClient([{}, {}], failures=failures)
    assert router.dispatch_request(
        value,
        target_client=target,
        dispatch_client=dispatch,
        repository_allowlist=frozenset({value.repository}),
    )
    assert "warning" in capsys.readouterr().out


def test_load_event_accepts_object_and_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert router.load_event(str(path)) == {"ok": True}
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        router.load_event(str(path))


def test_main_noop_for_untrusted_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event("no command")), encoding="utf-8")
    assert router.main(["--event-path", str(path)]) == 0
    assert "nothing to dispatch" in capsys.readouterr().out


def test_main_builds_clients_and_dispatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event()), encoding="utf-8")
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")
    monkeypatch.setenv("SOURCE_FIX_REPOSITORY_TARGETS", "ContextualWisdomLab/.github")
    clients: list[str] = []
    monkeypatch.setattr(router, "GitHubClient", lambda token: clients.append(token) or FakeClient())
    calls: list[router.SourceFixRequest] = []
    monkeypatch.setattr(router, "dispatch_request", lambda value, **kwargs: calls.append(value) or True)
    assert router.main(["--event-path", str(path), "--dry-run"]) == 0
    assert clients == ["target", "dispatch"]
    assert calls and calls[0].pull_request_number == 42


def test_main_requires_event_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    with pytest.raises(SystemExit):
        router.main([])
