"""Tests for trusted PR comment agent mention routing."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the router module from its script path."""

    module_name = "agent_mention_router"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def event(body: str, *, association: str = "MEMBER", user_type: str = "User") -> dict:
    """Build a representative issue-comment event with PR metadata attached."""

    return {
        "repository": {"full_name": "ContextualWisdomLab/example"},
        "issue": {"number": 17, "pull_request": {"url": "https://api.github.test/pr/17"}},
        "comment": {
            "id": 91,
            "body": body,
            "author_association": association,
            "user": {"login": "maintainer", "type": user_type},
        },
        "pull_request": {"head": {"sha": "a" * 40}},
    }


def test_parse_event_recognizes_both_exact_mentions() -> None:
    """Both supported exact mentions are emitted once in deterministic order."""

    module = load_module()
    request = module.parse_event(event("please @cwl-noema-review and @opencode-agent"))
    assert request is not None
    assert request.agents == ("cwl-noema-review", "opencode-agent")
    assert request.pull_request_head_sha == "a" * 40


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (event("no agent here"), None),
        (event("@opencode-agent", association="CONTRIBUTOR"), None),
        (event("@opencode-agent", user_type="Bot"), None),
        ({**event("@opencode-agent"), "issue": {"number": 17}}, None),
    ],
)
def test_parse_event_ignores_untrusted_or_irrelevant_comments(payload: dict, expected: None) -> None:
    """Non-PR, bot, untrusted, and unrelated comments do not dispatch work."""

    module = load_module()
    assert module.parse_event(payload) is expected


def test_parse_event_rejects_lookalike_mentions() -> None:
    """Agent-name prefixes and suffixes cannot trigger a dispatch."""

    module = load_module()
    assert module.parse_event(event("@opencode-agent-evil @cwl-noema-review2")) is None


def test_dispatch_reuses_existing_review_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """Noema and OpenCode mentions dispatch their established workflow events."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review @opencode-agent"))
    assert request is not None
    calls: list[tuple[list[str], dict | None]] = []

    def fake_gh_api(args, *, input_payload=None):
        calls.append((list(args), input_payload))

    monkeypatch.setattr(module, "gh_api", fake_gh_api)
    module.dispatch(request)

    dispatch_payloads = [payload for args, payload in calls if args[0].endswith("/dispatches")]
    assert [payload["event_type"] for payload in dispatch_payloads] == [
        "noema-review",
        "merge-scheduler",
    ]
    assert dispatch_payloads[1]["client_payload"]["requested_agent"] == "opencode-agent"
    assert calls[0][1] == {"content": "eyes"}
    assert "Queued @cwl-noema-review and @opencode-agent" in calls[-1][1]["body"]


def test_load_event_requires_json_object(tmp_path: Path) -> None:
    """Malformed event shapes fail closed before any GitHub mutation."""

    module = load_module()
    path = tmp_path / "event.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        module.load_event(str(path))
