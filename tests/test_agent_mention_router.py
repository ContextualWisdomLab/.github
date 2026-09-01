"""Tests for trusted PR comment agent mention routing."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


def receipt(comment_id: int, *, trusted: bool = True) -> dict:
    """Build one trusted or attacker-controlled receipt-looking comment."""

    return {
        "body": f"<!-- cwl-agent-mention-receipt:{comment_id} -->",
        "user": {
            "login": "github-actions[bot]" if trusted else "attacker",
            "type": "Bot" if trusted else "User",
        },
    }


def event(
    body: str,
    *,
    association: str = "MEMBER",
    user_type: str = "User",
) -> dict:
    """Build a representative enriched issue-comment event."""

    return {
        "repository": {"full_name": "ContextualWisdomLab/example"},
        "issue": {
            "number": 17,
            "pull_request": {"url": "https://api.github.test/pr/17"},
        },
        "comment": {
            "id": 91,
            "body": body,
            "author_association": association,
            "user": {"login": "maintainer", "type": user_type},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "develop", "sha": "b" * 40},
        },
    }


class FakeClient:
    """Capture JSON API calls for deterministic dispatch assertions."""

    def __init__(self) -> None:
        """Initialize an empty call ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Record one request and return an empty artifact inventory for reads."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/actions/artifacts"):
            return {"total_count": 0, "artifacts": []}
        return None


def repository_dispatch_calls(
    client: FakeClient,
) -> list[tuple[list[str], dict]]:
    """Return only mutation calls that enqueue central repository dispatches."""

    return [
        (args, payload)
        for args, payload in client.calls
        if args[0].endswith("/dispatches") and payload is not None
    ]


def test_exact_mentions_and_parse_event() -> None:
    """Both exact mentions are recognized with immutable PR metadata."""

    module = load_module()
    request = module.parse_event(
        event("please @cwl-noema-review and @opencode-agent")
    )
    assert request is not None
    assert request.agents == ("cwl-noema-review", "opencode-agent")
    assert request.pull_request_head_sha == "a" * 40
    assert request.pull_request_base_branch == "develop"
    assert request.pull_request_base_sha == "b" * 40
    assert module.exact_mentions("@opencode-agent-evil @cwl-noema-review2") == ()


@pytest.mark.parametrize(
    "body",
    [
        "/opencode please re-review",
        "/oc please re-review",
        "kicking off /oc",
        "/OC",
        "/OpenCode",
    ],
)
def test_exact_mentions_accepts_slash_opencode_aliases(body: str) -> None:
    """Upstream OpenCode's own /opencode and /oc trigger phrases also dispatch."""

    module = load_module()
    assert module.exact_mentions(body) == ("opencode-agent",)


def test_exact_mentions_accepts_at_mention_after_a_slash_separator() -> None:
    """A slash used to separate two agent requests must not swallow the @mention.

    Devin/owner review regression on #1537, across three rounds:

    1. Excluding a preceding ``/`` from the lookbehind to reject
       documentation-link false positives (see
       ``test_exact_mentions_rejects_slash_opencode_substrings``) was
       originally applied to the whole ``@opencode-agent|/opencode|/oc``
       alternation, so a maintainer separating both requested agents with a
       bare slash and no space (``@cwl-noema-review/@opencode-agent``)
       silently lost the OpenCode request.
    2. Simply exempting the ``@`` form from the slash exclusion reopened the
       same false-positive class for ``/@opencode-agent`` embedded in an
       arbitrary URL or path segment.
    3. Recognizing ``/@opencode-agent`` only when the slash is immediately
       preceded by the other pattern's exact literal mention text
       (``@cwl-noema-review``) checked only the boundary of the trailing
       slash, not whether that ``@cwl-noema-review`` occurrence itself has a
       valid left boundary, so invalid pasted text such as
       ``foo@cwl-noema-review/@opencode-agent`` still dispatched OpenCode
       (see ``test_exact_mentions_rejects_invalid_separator_prefixes``).

    The final pattern matches the whole separator form
    (``@cwl-noema-review/@opencode-agent``) as one literal, guarded by the
    same left-boundary exclusion as the standalone ``@opencode-agent``
    alternative.
    """

    module = load_module()
    assert module.exact_mentions("@cwl-noema-review/@opencode-agent") == (
        "cwl-noema-review",
        "opencode-agent",
    )


@pytest.mark.parametrize(
    "body",
    [
        "foo@cwl-noema-review/@opencode-agent",
        "docs/@cwl-noema-review/@opencode-agent",
        "user.name@cwl-noema-review/@opencode-agent",
    ],
)
def test_exact_mentions_rejects_invalid_separator_prefixes(body: str) -> None:
    """The combined separator literal must not fire when embedded in a larger token.

    Fifth-round finding on #1537, reported directly by the repository owner
    (not a review bot): the separator alternative
    ``(?<=@cwl-noema-review)/@opencode-agent`` only checked the literal text
    immediately before the slash, not whether that ``@cwl-noema-review``
    occurrence itself has a valid left boundary. Pasted text embedding the
    Noema mention inside a larger token — a preceding word
    (``foo@cwl-noema-review/@opencode-agent``), a path segment
    (``docs/@cwl-noema-review/@opencode-agent``), or an email-like local part
    (``user.name@cwl-noema-review/@opencode-agent``) — still dispatched an
    unintended OpenCode review. The fix matches the whole
    ``@cwl-noema-review/@opencode-agent`` literal with the same left-boundary
    exclusion as the standalone ``@opencode-agent`` alternative, so it no
    longer fires unless the combined mention itself starts at a valid
    boundary. Some of these inputs still independently match the unrelated,
    pre-existing ``cwl-noema-review`` pattern (e.g. a preceding ``/`` is not
    excluded there); that pattern predates this PR and is out of scope for
    this fix, so only the OpenCode dispatch is asserted here.
    """

    module = load_module()
    assert "opencode-agent" not in module.exact_mentions(body)


@pytest.mark.parametrize(
    "body",
    [
        "the /occupied seat",
        "visit /oceanography for more",
        "see /opencode-docs for the guide",
        "check out https://opencode.ai/docs for more info",
        "see http://open-code.ai/en/docs/github",
        "share this: https://youtube.com/@opencode-agent",
        "see docs/@opencode-agent for the config file",
        "visit https://example.com/?next=/opencode for the redirect",
        "visit https://example.com/?next=/oc for the redirect",
    ],
)
def test_exact_mentions_rejects_slash_opencode_substrings(body: str) -> None:
    """A longer token merely starting with /oc or /opencode is not a mention.

    Includes a URL whose path component happens to embed ``/opencode`` right
    after the scheme's own ``//`` (Devin review finding on #1537): the prior
    lookbehind excluded a preceding letter/digit/underscore/hyphen but not a
    preceding ``/``, so a documentation link like ``https://opencode.ai``
    satisfied it and could launch an unintended review. Also includes a
    second-round Devin finding on the same PR: restoring plain recognition of
    ``@opencode-agent`` after a bare slash (so a maintainer could write
    ``@cwl-noema-review/@opencode-agent`` with no space) reopened the same
    class of false positive for ``/@opencode-agent`` embedded in an arbitrary
    URL or path segment, since both share the exact same "word char, then
    slash, then the mention" shape as the deliberate separator case. A third
    finding (CodeRabbit, same PR) noted the slash-preceded exclusion for the
    bare ``/opencode``/``/oc`` forms did not also exclude a preceding ``=``,
    so a URL query string such as ``?next=/opencode`` or ``?next=/oc`` still
    matched.
    """

    module = load_module()
    assert module.exact_mentions(body) == ()


@pytest.mark.parametrize(
    "body",
    [
        "/oc/config",
        "/opencode/docs",
        "@opencode-agent/config",
        "@cwl-noema-review/@opencode-agent/foo",
    ],
)
def test_exact_mentions_rejects_trailing_path_continuation(body: str) -> None:
    """A root-relative path continuation right after the alias is not a mention.

    Sixth-round finding on #1537's successor PR (Devin): the shared trailing
    boundary after all three ``opencode-agent`` alternatives excluded a
    following letter, digit, underscore, or hyphen but not a following
    ``/``, so a root-relative path glued directly onto the alias — ``/oc``
    followed by ``/config``, ``/opencode`` followed by ``/docs``, or even
    ``@opencode-agent`` or the ``@cwl-noema-review/@opencode-agent``
    separator followed by ``/config`` or ``/foo`` — still matched as a
    complete, valid mention, since nothing treated the alias text itself as
    incomplete just because a slash continued right after it. The fix adds
    ``/`` to the shared trailing exclusion, mirroring the leading-boundary
    ``/`` exclusion already applied to each alternative from the other side.
    """

    module = load_module()
    assert "opencode-agent" not in module.exact_mentions(body)


@pytest.mark.parametrize(
    "body",
    [
        "/oc?mode=docs",
        "/opencode?next=x",
    ],
)
def test_exact_mentions_rejects_trailing_query_string(body: str) -> None:
    """A query string glued directly onto the bare slash alias is not a mention.

    Seventh-round finding on #1537's successor PR (CodeRabbit): the bare
    ``/opencode``/``/oc`` forms' trailing boundary excluded a following
    letter, digit, underscore, hyphen, or slash, but not a following ``?``,
    so a query string with no separator (``/oc?mode=docs``,
    ``/opencode?next=x``) still matched as a complete mention. The fix adds
    ``?`` to that alternative's own trailing exclusion only — see
    ``test_exact_mentions_accepts_ordinary_punctuation_after_at_mentions``
    for why this must NOT be shared with the ``@``-mention alternatives.
    """

    module = load_module()
    assert "opencode-agent" not in module.exact_mentions(body)


def test_exact_mentions_accepts_ordinary_punctuation_after_at_mentions() -> None:
    """A trailing "?" after an @-mention is ordinary punctuation, not a mention.

    Ninth-round finding on #1537's successor PR (Devin), a regression from
    the eighth-round fix above: excluding a trailing ``?`` was applied to
    the whole ``opencode-agent`` alternation instead of scoped to only the
    bare-slash forms it was meant for, so a maintainer ending a sentence
    with ``@opencode-agent?`` (or the ``@cwl-noema-review/@opencode-agent``
    separator followed by ``?``) silently stopped dispatching. Each
    alternative now carries its own trailing lookahead instead of one
    shared across the alternation, so the bare-slash forms' ``?`` exclusion
    no longer leaks onto the ``@``-mention forms.
    """

    module = load_module()
    assert module.exact_mentions("@opencode-agent?") == ("opencode-agent",)
    assert module.exact_mentions("@cwl-noema-review/@opencode-agent?") == (
        "cwl-noema-review",
        "opencode-agent",
    )


@pytest.mark.parametrize(
    "body",
    [
        "https://example.com/#/oc",
        "https://example.com/#/opencode",
        "/oc.json",
        "/opencode.json",
        "/océan",
    ],
)
def test_exact_mentions_rejects_fragment_dotted_and_unicode_continuations(
    body: str,
) -> None:
    """A URL fragment, dotted filename, or Unicode word continuation is not a mention.

    Eighth-round finding on #1537's successor PR (Devin): the bare
    ``/opencode``/``/oc`` forms' boundary excluded neither a preceding
    ``#`` (a URL fragment identifier, ``https://example.com/#/oc``) nor a
    following ``.`` (a dotted filename continuation, ``/oc.json``), and
    used a plain ASCII character class for the trailing boundary, which
    does not exclude a following non-ASCII word character (``/océan``,
    where ``é`` is a Unicode letter but not in ``[A-Za-z0-9_/?-]``). The fix
    adds ``#`` and ``.`` to that alternative's own leading/trailing
    exclusion set and switches every boundary in this module from an
    ASCII-only character class to Python's Unicode-aware ``\\w``.
    """

    module = load_module()
    assert "opencode-agent" not in module.exact_mentions(body)


def test_exact_mentions_rejects_unicode_embedded_at_mentions() -> None:
    """A Unicode word character directly touching an @-mention is not a mention.

    Companion case to the eighth-round Unicode finding above, for the
    ``@``-mention alternatives rather than the bare-slash forms: switching
    their boundaries to Unicode-aware ``\\w`` closes the same class of gap
    (a preceding or following accented letter that a plain ASCII character
    class would not have excluded).
    """

    module = load_module()
    assert module.exact_mentions("café@opencode-agent") == ()
    assert module.exact_mentions("@opencode-agenté") == ()


@pytest.mark.parametrize(
    "payload",
    [
        event("no agent here"),
        event("@opencode-agent", association="CONTRIBUTOR"),
        event("@opencode-agent", user_type="Bot"),
        {**event("@opencode-agent"), "issue": {"number": 17}},
        {
            **event("@opencode-agent"),
            "pull_request": {
                **event("@opencode-agent")["pull_request"],
                "state": "closed",
            },
        },
        {
            **event("@opencode-agent"),
            "conversation_comments": [receipt(91)],
        },
    ],
)
def test_parse_event_ignores_untrusted_irrelevant_or_processed_comments(
    payload: dict,
) -> None:
    """Untrusted, irrelevant, non-PR, and acknowledged comments are ignored."""

    assert load_module().parse_event(payload) is None


def test_untrusted_receipt_marker_cannot_suppress_invocation() -> None:
    """A user-authored marker does not acknowledge a trusted invocation."""

    payload = event("@opencode-agent")
    payload["conversation_comments"] = [receipt(91, trusted=False)]
    assert load_module().parse_event(payload) is not None


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("repository", "full_name"), "outside/example", "limited"),
        (("issue", "number"), 0, "number"),
        (("comment", "id"), 0, "comment id"),
        (("pull_request", "head", "sha"), "bad", "head SHA"),
        (("pull_request", "base", "ref"), "-bad", "base branch"),
        (("pull_request", "base", "sha"), "bad", "base SHA"),
        (("comment", "user", "login"), "", "actor"),
    ],
)
def test_parse_event_rejects_malformed_trusted_requests(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    """Malformed trusted invocation metadata fails closed."""

    payload = event("@opencode-agent")
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=message):
        load_module().parse_event(payload)


def test_receipt_and_allowlist_helpers() -> None:
    """Receipt extraction and exact repository allowlists are deterministic."""

    module = load_module()
    assert module.receipt_marker(91) == "<!-- cwl-agent-mention-receipt:91 -->"
    with pytest.raises(ValueError, match="positive"):
        module.receipt_marker(0)
    comments = [
        receipt(91),
        {
            "body": "x <!-- cwl-agent-mention-receipt:92 --> y",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        },
        receipt(93, trusted=False),
        {"body": None, "user": {"login": "github-actions[bot]", "type": "Bot"}},
    ]
    assert module.processed_comment_ids(comments) == frozenset({91, 92})
    assert module.parse_repository_allowlist(
        "ContextualWisdomLab/example, ContextualWisdomLab/.github,"
    ) == frozenset(
        {"ContextualWisdomLab/example", "ContextualWisdomLab/.github"}
    )
    with pytest.raises(ValueError, match="invalid repository"):
        module.parse_repository_allowlist("outside/example")


def test_eligible_agents_and_payloads() -> None:
    """Eligibility and event bodies preserve the bounded review contract."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review @opencode-agent"))
    assert request is not None
    assert module.eligible_agents(
        request,
        opencode_allowlist=frozenset({request.repository}),
    ) == (("cwl-noema-review", "opencode-agent"), ())
    assert module.eligible_agents(
        request,
        opencode_allowlist=frozenset(),
    ) == (("cwl-noema-review",), ("opencode-agent",))
    noema = module.noema_payload(request)
    assert noema["event_type"] == "agent-mention-noema"
    assert noema["client_payload"]["pr_head_sha"] == "a" * 40
    assert noema["client_payload"]["pr_base_sha"] == "b" * 40
    opencode = module.opencode_payload(request)
    assert opencode["event_type"] == "agent-mention-opencode"
    assert opencode["client_payload"]["base_branch"] == "develop"
    assert opencode["client_payload"]["pr_base_sha"] == "b" * 40
    assert "merge_mode" not in opencode["client_payload"]
    assert "enable_auto_merge" not in opencode["client_payload"]
    assert "update_branches" not in opencode["client_payload"]
    claim = module.agent_invocation_claim(request, "opencode-agent")
    assert claim["merge_mode"] == "disabled"
    assert claim["enable_auto_merge"] is False
    assert claim["update_branches"] is False


def test_dispatch_uses_central_events_and_acknowledges() -> None:
    """Both agents dispatch centrally with bounded review-only OpenCode options."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review @opencode-agent"))
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    result = module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset({request.repository}),
    )
    assert result == ("@cwl-noema-review", "@opencode-agent")
    dispatches = repository_dispatch_calls(central)
    assert [payload["event_type"] for _, payload in dispatches] == [
        "agent-mention-noema",
        "agent-mention-opencode",
    ]
    assert all(
        args[0] == "repos/ContextualWisdomLab/.github/dispatches"
        for args, _ in dispatches
    )
    assert target.calls[0][1] == {"content": "eyes"}
    assert "cwl-agent-mention-receipt:91" in target.calls[1][1]["body"]
    assert "exact-name Actions artifacts" in target.calls[1][1]["body"]


def test_dispatch_rejects_unallowlisted_opencode_and_supports_dry_run(
    capsys,
) -> None:
    """Rejected-only and dry-run requests remain mutation-free."""

    module = load_module()
    request = module.parse_event(event("@opencode-agent"))
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ()
    assert target.calls == central.calls == []
    assert "Rejected agent mention without target mutation" in capsys.readouterr().out

    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
        dry_run=True,
    ) == ()
    assert target.calls == central.calls == []
    output = capsys.readouterr().out
    assert "DRY-RUN agent mention" in output
    assert "reject=opencode-agent" in output


def test_dispatch_noema_only_covers_non_opencode_path() -> None:
    """A Noema-only request bypasses the OpenCode allowlist branch."""

    module = load_module()
    request = module.parse_event(event("@cwl-noema-review"))
    assert request is not None
    target = FakeClient()
    central = FakeClient()
    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)
    dispatches = repository_dispatch_calls(central)
    assert len(dispatches) == 1
    assert dispatches[0][1]["event_type"] == "agent-mention-noema"


def test_github_client_validates_token_and_decodes_json(monkeypatch) -> None:
    """The token-bound client never places credentials in command arguments."""

    module = load_module()
    with pytest.raises(ValueError, match="token"):
        module.GitHubClient("")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout='{"ok": true}\n')

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    client = module.GitHubClient("secret-token")
    assert client.request(["repos/x/y"], input_payload={"a": 1}) == {"ok": True}
    command, kwargs = calls[0]
    assert command == ["gh", "api", "repos/x/y", "--input", "-"]
    assert "secret-token" not in command
    assert kwargs["env"]["GH_TOKEN"] == "secret-token"
    assert kwargs["input"] == '{"a": 1}'
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="  "),
    )
    assert client.request(["repos/x/y"]) is None


def test_load_event_and_main_paths(tmp_path: Path, monkeypatch, capsys) -> None:
    """CLI rejects malformed JSON, ignores irrelevant events, and dispatches input."""

    module = load_module()
    array_path = tmp_path / "array.json"
    array_path.write_text(json.dumps(["bad"]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        module.load_event(str(array_path))
    ignored_path = tmp_path / "ignored.json"
    ignored_path.write_text(json.dumps(event("nothing")), encoding="utf-8")
    assert module.main(["--event-path", str(ignored_path)]) == 0
    assert "nothing to dispatch" in capsys.readouterr().out
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    with pytest.raises(SystemExit):
        module.main([])
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(event("@opencode-agent")), encoding="utf-8")
    captured = []
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv(
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS",
        "ContextualWisdomLab/example",
    )
    monkeypatch.setattr(
        module,
        "dispatch_request",
        lambda request, **kwargs: captured.append((request, kwargs)) or (),
    )
    assert module.main(["--event-path", str(valid_path), "--dry-run"]) == 0
    assert captured[0][1]["dry_run"] is True
