"""Fail-closed tests for protected pull-request head publication."""

from __future__ import annotations

import copy
import json

import pytest

from scripts.ci import pr_head_publisher as publisher

EXPECTED_HEAD = "a" * 40
LOCAL_HEAD = "b" * 40


def original_pr(*, head_sha: str = EXPECTED_HEAD) -> dict:
    """Return the exact same-repository pull request guarded by a publication."""

    return {
        "number": 7,
        "state": "open",
        "base": {"ref": "main"},
        "head": {
            "ref": "feature/topic",
            "sha": head_sha,
            "repo": {"full_name": "owner/repo"},
        },
    }


def fork_repository() -> dict:
    """Return a valid user-owned fork of the target repository."""

    return {
        "full_name": "actor/repo",
        "fork": True,
        "owner": {"login": "actor"},
        "parent": {"full_name": "owner/repo"},
    }


def stack_pr(branch: str, *, number: int = 91) -> dict:
    """Return an open protected-publication stack pull request."""

    marker = f"<!-- cwl-protected-publication owner/repo#7@{EXPECTED_HEAD} -->"
    return {
        "number": number,
        "state": "open",
        "html_url": f"https://github.com/owner/repo/pull/{number}",
        "body": marker,
        "base": {"ref": "feature/topic"},
        "head": {
            "ref": branch,
            "sha": LOCAL_HEAD,
            "repo": {"full_name": "actor/repo"},
        },
    }


def test_direct_publication_verifies_the_new_live_head(monkeypatch):
    """A normal push remains the shortest path and verifies its resulting head."""

    gh_calls = []
    git_calls = []
    live_heads = iter((EXPECTED_HEAD, LOCAL_HEAD))

    def fake_run(args, *, stdin=None):
        gh_calls.append((args, stdin))
        assert args[:2] == ["gh", "api"]
        return json.dumps(original_pr(head_sha=next(live_heads)))

    def fake_run_with_env(args, *, stdin=None, env=None):
        git_calls.append((args, env))
        if args[-2:] == ["rev-parse", "HEAD"]:
            return f"{LOCAL_HEAD}\n"
        assert args[-1] == "HEAD:refs/heads/feature/topic"
        assert "x-access-token" not in " ".join(args)
        assert env and env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
        return ""

    monkeypatch.setattr(publisher, "run", fake_run)
    monkeypatch.setattr(publisher, "run_with_env", fake_run_with_env)

    result = publisher.publish_head(
        "/work",
        "owner/repo",
        7,
        "feature/topic",
        EXPECTED_HEAD,
        token="secret-token",
        kind="review",
    )

    assert result.mode == "direct"
    assert result.head_repository == "owner/repo"
    assert result.head_ref == "feature/topic"
    assert result.pull_number is None
    assert len(gh_calls) == 2
    assert len(git_calls) == 2


def test_only_exact_pull_request_gh013_enters_fork_fallback(monkeypatch):
    """An unrelated push failure stays fatal and never asks GitHub for a user fork."""

    gh_calls = []

    def fake_run(args, *, stdin=None):
        gh_calls.append(args)
        return json.dumps(original_pr())

    def fake_run_with_env(args, *, stdin=None, env=None):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return LOCAL_HEAD
        raise RuntimeError("Command failed: remote HTTP 500")

    monkeypatch.setattr(publisher, "run", fake_run)
    monkeypatch.setattr(publisher, "run_with_env", fake_run_with_env)

    with pytest.raises(RuntimeError, match="HTTP 500"):
        publisher.publish_head(
            "/work",
            "owner/repo",
            7,
            "feature/topic",
            EXPECTED_HEAD,
            token="secret-token",
            kind="review",
        )
    assert all(call[:3] != ["gh", "api", "user"] for call in gh_calls)


def test_gh013_creates_user_fork_branch_and_stacked_pr(monkeypatch):
    """The exact PR-required rejection opens one non-maintainable upstream stack."""

    fork_exists = False
    fork_sha = None
    posted_payloads = []
    stack_branch = f"cwl-autofix/pr-7-{EXPECTED_HEAD[:12]}"

    def fake_run(args, *, stdin=None):
        nonlocal fork_exists
        endpoint = next((value for value in args if value.startswith("repos/")), "")
        if args == ["gh", "api", "user"]:
            return json.dumps({"login": "actor"})
        if endpoint == "repos/owner/repo/pulls/7":
            return json.dumps(original_pr())
        if endpoint == "repos/actor/repo":
            if not fork_exists:
                raise RuntimeError("gh: Not Found (HTTP 404)")
            return json.dumps(fork_repository())
        if args[:3] == ["gh", "repo", "fork"]:
            fork_exists = True
            return ""
        if endpoint.startswith("repos/owner/repo/pulls?"):
            return "[]"
        if endpoint.startswith("repos/actor/repo/git/ref/heads/"):
            if fork_sha is None:
                raise RuntimeError("gh: Not Found (HTTP 404)")
            return json.dumps({"object": {"sha": fork_sha}})
        if endpoint == "repos/owner/repo/pulls" and "POST" in args:
            payload = json.loads(stdin)
            posted_payloads.append(payload)
            return json.dumps(stack_pr(stack_branch))
        raise AssertionError(args)

    def fake_run_with_env(args, *, stdin=None, env=None):
        nonlocal fork_sha
        if args[-2:] == ["rev-parse", "HEAD"]:
            return LOCAL_HEAD
        destination = args[-2]
        if destination == "https://github.com/owner/repo.git":
            raise RuntimeError(
                "remote: error: GH013: Repository rule violations found\n"
                "remote: - Changes must be made through a pull request"
            )
        assert destination == "https://github.com/actor/repo.git"
        assert args[-1] == f"HEAD:refs/heads/{stack_branch}"
        fork_sha = LOCAL_HEAD
        return ""

    monkeypatch.setattr(publisher, "run", fake_run)
    monkeypatch.setattr(publisher, "run_with_env", fake_run_with_env)

    result = publisher.publish_head(
        "/work",
        "owner/repo",
        7,
        "feature/topic",
        EXPECTED_HEAD,
        token="secret-token",
        kind="review",
    )

    assert result.mode == "stacked"
    assert result.pull_number == 91
    assert result.head_repository == "actor/repo"
    assert result.head_ref == stack_branch
    assert posted_payloads == [
        {
            "title": "fix(pr-7): publish protected review repair",
            "head": f"actor:{stack_branch}",
            "base": "feature/topic",
            "body": publisher.stack_body("owner/repo", 7, EXPECTED_HEAD, "review"),
            "maintainer_can_modify": False,
        }
    ]


def test_head_drift_after_rejected_push_stops_before_fork(monkeypatch):
    """A moved original head cannot receive a stale stacked repair."""

    live_heads = iter((EXPECTED_HEAD, "c" * 40))
    seen_user = False

    def fake_run(args, *, stdin=None):
        nonlocal seen_user
        if args[:3] == ["gh", "api", "user"]:
            seen_user = True
        return json.dumps(original_pr(head_sha=next(live_heads)))

    def fake_run_with_env(args, *, stdin=None, env=None):
        if args[-2:] == ["rev-parse", "HEAD"]:
            return LOCAL_HEAD
        raise RuntimeError(
            "remote: error: GH013: Repository rule violations found\n"
            "remote: - Changes must be made through a pull request"
        )

    monkeypatch.setattr(publisher, "run", fake_run)
    monkeypatch.setattr(publisher, "run_with_env", fake_run_with_env)

    with pytest.raises(RuntimeError, match="head moved"):
        publisher.publish_head(
            "/work",
            "owner/repo",
            7,
            "feature/topic",
            EXPECTED_HEAD,
            token="secret-token",
            kind="conflict",
        )
    assert not seen_user


def test_json_server_and_force_push_boundaries(monkeypatch):
    """Reject malformed transport data and keep force-with-lease explicit."""

    monkeypatch.setattr(publisher, "run", lambda *a, **k: "not-json")
    with pytest.raises(RuntimeError, match="malformed JSON"):
        publisher._json(["gh", "api", "x"])

    assert publisher._server_url("https://github.example/") == "https://github.example"
    with pytest.raises(ValueError, match="canonical HTTPS"):
        publisher._server_url("http://github.example")

    captured = {}
    monkeypatch.setattr(
        publisher,
        "run_with_env",
        lambda args, **kwargs: captured.update(args=args, env=kwargs["env"]) or "",
    )
    publisher._push(
        "/work",
        "owner/repo",
        "feature",
        token="token",
        server_url="https://github.com",
        force_with_lease=EXPECTED_HEAD,
    )
    assert (
        f"--force-with-lease=refs/heads/feature:{EXPECTED_HEAD}" in captured["args"]
    )
    assert "token" not in " ".join(captured["args"])


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ([], "malformed original"),
        ({**original_pr(), "state": "closed"}, "no longer open"),
        (
            {
                **original_pr(),
                "head": {
                    **original_pr()["head"],
                    "repo": {"full_name": "other/repo"},
                },
            },
            "repository or branch changed",
        ),
        (
            {
                **original_pr(),
                "head": {**original_pr()["head"], "ref": "other"},
            },
            "repository or branch changed",
        ),
    ),
)
def test_original_pull_request_shape_and_identity_fail_closed(
    monkeypatch, payload, message
):
    """Require one open same-repository branch before publication."""

    monkeypatch.setattr(publisher, "_json", lambda *a, **k: payload)
    with pytest.raises(RuntimeError, match=message):
        publisher._original_pr(
            "owner/repo", 7, "feature/topic", EXPECTED_HEAD
        )


def test_user_identity_and_repository_lookup_fail_closed(monkeypatch):
    """An app-only token or malformed repository cannot become a fork owner."""

    monkeypatch.setattr(
        publisher,
        "_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 403")),
    )
    with pytest.raises(RuntimeError, match="user credential"):
        publisher._user_login()

    monkeypatch.setattr(publisher, "_json", lambda *a, **k: {})
    with pytest.raises(RuntimeError, match="fork owner login"):
        publisher._user_login()
    monkeypatch.setattr(publisher, "_json", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="malformed repository"):
        publisher._repository_or_none("actor/repo")

    monkeypatch.setattr(
        publisher,
        "_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 500")),
    )
    with pytest.raises(RuntimeError, match="500"):
        publisher._repository_or_none("actor/repo")


@pytest.mark.parametrize(
    "change",
    (
        {"fork": False},
        {"full_name": "actor/not-repo"},
        {"parent": {"full_name": "other/repo"}},
        {"owner": {"login": "other"}},
    ),
)
def test_existing_fork_must_match_every_identity_axis(monkeypatch, change):
    """Reject same-name repositories that are not the actor fork of the target."""

    payload = fork_repository()
    payload.update(change)
    monkeypatch.setattr(publisher, "_repository_or_none", lambda repo: payload)
    with pytest.raises(RuntimeError, match="not the expected"):
        publisher._ensure_fork("owner/repo", "actor")


def test_fork_creation_races_and_materialization(monkeypatch):
    """Reuse a concurrently created fork and reject a fork that never appears."""

    payload = fork_repository()
    responses = iter((None, payload, payload))
    monkeypatch.setattr(
        publisher, "_repository_or_none", lambda repo: next(responses)
    )
    monkeypatch.setattr(
        publisher,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("already exists")),
    )
    assert publisher._ensure_fork("owner/repo", "actor") == "actor/repo"

    monkeypatch.setattr(publisher, "_repository_or_none", lambda repo: None)
    monkeypatch.setattr(publisher, "run", lambda *a, **k: "")
    with pytest.raises(RuntimeError, match="did not materialize"):
        publisher._ensure_fork("owner/repo", "actor")

    monkeypatch.setattr(
        publisher,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fork denied")),
    )
    with pytest.raises(RuntimeError, match="fork denied"):
        publisher._ensure_fork("owner/repo", "actor")


def test_fork_ref_rejects_non404_and_malformed_responses(monkeypatch):
    """Only a real 404 means a publication branch is absent."""

    monkeypatch.setattr(
        publisher,
        "_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 500")),
    )
    with pytest.raises(RuntimeError, match="500"):
        publisher._fork_ref_sha("actor/repo", "branch")

    monkeypatch.setattr(publisher, "_json", lambda *a, **k: {})
    with pytest.raises(RuntimeError, match="malformed fork branch"):
        publisher._fork_ref_sha("actor/repo", "branch")


def test_fork_ref_keeps_branch_slashes_as_path_segments(monkeypatch):
    """GitHub ref lookups preserve slash-separated branch path segments."""
    calls = []

    def fake_json(args, **kwargs):
        calls.append(args)
        return {"object": {"sha": LOCAL_HEAD}}

    monkeypatch.setattr(publisher, "_json", fake_json)

    assert publisher._fork_ref_sha("actor/repo", "cwl-autofix/pr-7-head") == LOCAL_HEAD
    assert calls == [[
        "gh",
        "api",
        "repos/actor/repo/git/ref/heads/cwl-autofix/pr-7-head",
    ]]


def _stack_result(payload):
    """Validate one test stack through the production identity contract."""

    return publisher._stack_result(
        payload,
        repo="owner/repo",
        pr_number=7,
        expected_head_sha=EXPECTED_HEAD,
        local_head_sha=LOCAL_HEAD,
        fork_repo="actor/repo",
        fork_ref="stack",
        head_ref="feature/topic",
    )


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: [],
        lambda value: {**value, "state": "closed"},
        lambda value: {**value, "number": "91"},
        lambda value: {**value, "number": 0},
        lambda value: {**value, "html_url": None},
        lambda value: {**value, "base": {"ref": "other"}},
        lambda value: {**value, "head": {**value["head"], "ref": "other"}},
        lambda value: {**value, "head": {**value["head"], "sha": "c" * 40}},
        lambda value: {
            **value,
            "head": {**value["head"], "repo": {"full_name": "other/repo"}},
        },
        lambda value: {**value, "body": "missing marker"},
    ),
)
def test_stacked_pull_request_validates_all_identity_fields(mutator):
    """Reject a stack that is stale, malformed, hijacked, or marker-free."""

    valid = stack_pr("stack")
    with pytest.raises(RuntimeError, match="stacked pull request"):
        _stack_result(mutator(copy.deepcopy(valid)))


def test_open_stack_list_shape_count_and_reuse(monkeypatch):
    """A deterministic branch has zero or one reusable live stack."""

    monkeypatch.setattr(publisher, "_json", lambda *a, **k: {})
    with pytest.raises(RuntimeError, match="malformed stacked pull-request list"):
        publisher._open_stack(
            "owner/repo", 7, EXPECTED_HEAD, LOCAL_HEAD, "actor/repo", "stack", "feature/topic"
        )

    monkeypatch.setattr(
        publisher, "_json", lambda *a, **k: [stack_pr("stack"), stack_pr("stack", number=92)]
    )
    with pytest.raises(RuntimeError, match="multiple live"):
        publisher._open_stack(
            "owner/repo", 7, EXPECTED_HEAD, LOCAL_HEAD, "actor/repo", "stack", "feature/topic"
        )

    monkeypatch.setattr(publisher, "_json", lambda *a, **k: [stack_pr("stack")])
    result = publisher._open_stack(
        "owner/repo", 7, EXPECTED_HEAD, LOCAL_HEAD, "actor/repo", "stack", "feature/topic"
    )
    assert result and result.pull_number == 91

    stale = stack_pr("stack")
    stale["head"]["sha"] = "c" * 40
    monkeypatch.setattr(publisher, "_json", lambda *a, **k: [stale])
    assert publisher._open_stack(
        "owner/repo", 7, EXPECTED_HEAD, LOCAL_HEAD, "actor/repo", "stack", "feature/topic"
    ) is None


def test_publication_branch_uses_safe_secondary_without_overwrite(monkeypatch):
    """A closed divergent primary stack gets a new non-force output branch."""

    values = iter(("c" * 40, None))
    monkeypatch.setattr(publisher, "_fork_ref_sha", lambda *a: next(values))
    assert publisher._publication_branch(
        "actor/repo", 7, EXPECTED_HEAD, LOCAL_HEAD
    ) == f"cwl-autofix/pr-7-{EXPECTED_HEAD[:12]}-{LOCAL_HEAD[:12]}"

    values = iter(("c" * 40, LOCAL_HEAD))
    monkeypatch.setattr(publisher, "_fork_ref_sha", lambda *a: next(values))
    assert publisher._publication_branch(
        "actor/repo", 7, EXPECTED_HEAD, LOCAL_HEAD
    ).endswith(LOCAL_HEAD[:12])

    values = iter(("c" * 40, "d" * 40))
    monkeypatch.setattr(publisher, "_fork_ref_sha", lambda *a: next(values))
    with pytest.raises(RuntimeError, match="prefix collision"):
        publisher._publication_branch(
            "actor/repo", 7, EXPECTED_HEAD, LOCAL_HEAD
        )


def _configure_stack_unit(monkeypatch, open_results, ref_results):
    """Install deterministic internal collaborators for stack branch tests."""

    monkeypatch.setattr(publisher, "_user_login", lambda: "actor")
    monkeypatch.setattr(publisher, "_ensure_fork", lambda *a: "actor/repo")
    monkeypatch.setattr(
        publisher, "_open_stack", lambda *a: next(open_results)
    )
    monkeypatch.setattr(
        publisher, "_publication_branch", lambda *a: "stack"
    )
    monkeypatch.setattr(
        publisher, "_fork_ref_sha", lambda *a: next(ref_results)
    )


def test_create_stack_reuses_primary_and_selected_branch(monkeypatch):
    """Return any matching in-flight stack before mutating its fork."""

    existing = publisher.PublicationResult(
        "stacked", "actor/repo", "stack", 91, "url"
    )
    _configure_stack_unit(monkeypatch, iter((existing,)), iter(()))
    assert publisher._create_stack(
        "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
        token="token", server_url="https://github.com"
    ) is existing

    _configure_stack_unit(monkeypatch, iter((None, existing)), iter(()))
    assert publisher._create_stack(
        "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
        token="token", server_url="https://github.com"
    ) is existing


def test_create_stack_verifies_fork_push_and_concurrent_stack(monkeypatch):
    """Verify the fork ref and reuse a stack created during publication."""

    existing = publisher.PublicationResult(
        "stacked", "actor/repo", "stack", 91, "url"
    )
    _configure_stack_unit(
        monkeypatch,
        iter((None, None, existing)),
        iter((None, LOCAL_HEAD)),
    )
    pushed = []
    monkeypatch.setattr(publisher, "_push", lambda *a, **k: pushed.append(True))
    monkeypatch.setattr(publisher, "_original_pr", lambda *a: original_pr())
    assert publisher._create_stack(
        "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
        token="token", server_url="https://github.com"
    ) is existing
    assert pushed == [True]

    _configure_stack_unit(
        monkeypatch,
        iter((None, None)),
        iter((None, "c" * 40)),
    )
    monkeypatch.setattr(publisher, "_push", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="did not reach"):
        publisher._create_stack(
            "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
            token="token", server_url="https://github.com"
        )


def test_create_stack_recovers_create_race_or_reraises(monkeypatch):
    """A concurrent identical PR is reused; an unrelated create error stays fatal."""

    existing = publisher.PublicationResult(
        "stacked", "actor/repo", "stack", 91, "url"
    )
    _configure_stack_unit(
        monkeypatch,
        iter((None, None, None, existing)),
        iter((LOCAL_HEAD, LOCAL_HEAD)),
    )
    monkeypatch.setattr(publisher, "_original_pr", lambda *a: original_pr())
    monkeypatch.setattr(
        publisher,
        "_json",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("create race")),
    )
    assert publisher._create_stack(
        "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
        token="token", server_url="https://github.com"
    ) is existing

    _configure_stack_unit(
        monkeypatch,
        iter((None, None, None, None)),
        iter((LOCAL_HEAD, LOCAL_HEAD)),
    )
    with pytest.raises(RuntimeError, match="create race"):
        publisher._create_stack(
            "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
            token="token", server_url="https://github.com"
        )


@pytest.mark.parametrize("close_fails", (False, True))
def test_created_stack_closes_if_original_head_moves(monkeypatch, close_fails):
    """Close a newly created stale stack, and surface closure failure separately."""

    _configure_stack_unit(
        monkeypatch,
        iter((None, None, None)),
        iter((LOCAL_HEAD, LOCAL_HEAD)),
    )
    created = stack_pr("stack")
    created["base"] = {"ref": "feature"}
    monkeypatch.setattr(publisher, "_json", lambda *a, **k: created)
    original_calls = 0

    def moved_original(*args):
        nonlocal original_calls
        original_calls += 1
        if original_calls > 1:
            raise RuntimeError("head moved")
        return original_pr()

    monkeypatch.setattr(publisher, "_original_pr", moved_original)

    def close(args, *, stdin=None):
        if close_fails:
            raise RuntimeError("close failed")
        return ""

    monkeypatch.setattr(publisher, "run", close)
    message = "closure failed" if close_fails else "stale stack closed"
    with pytest.raises(RuntimeError, match=message):
        publisher._create_stack(
            "/w", "owner/repo", 7, "feature", EXPECTED_HEAD, LOCAL_HEAD, "review",
            token="token", server_url="https://github.com"
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"pr_number": 0}, "positive"),
        ({"kind": "unknown"}, "publication kind"),
        ({"token": ""}, "token is required"),
        ({"server_url": "http://github.com"}, "canonical HTTPS"),
    ),
)
def test_publication_input_validation(monkeypatch, kwargs, message):
    """Reject invalid mutation identity before any Git or GitHub call."""

    values = {
        "workdir": "/w",
        "repo": "owner/repo",
        "pr_number": 7,
        "head_ref": "feature",
        "expected_head_sha": EXPECTED_HEAD,
        "token": "token",
        "kind": "review",
    }
    values.update(kwargs)
    monkeypatch.setattr(
        publisher, "_git_head", lambda *a: pytest.fail("must validate first")
    )
    with pytest.raises(ValueError, match=message):
        publisher.publish_head(**values)


def test_main_forwards_environment_token_and_prints_json(monkeypatch, capsys):
    """The workflow CLI forwards exact arguments without placing its token in argv."""

    seen = {}
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(
        publisher,
        "publish_head",
        lambda *args, **kwargs: seen.update(args=args, kwargs=kwargs)
        or publisher.PublicationResult("direct", "owner/repo", "feature"),
    )
    assert publisher.main(
        [
            "--workdir", "/w",
            "--repo", "owner/repo",
            "--pr-number", "7",
            "--head-ref", "feature",
            "--expected-head-sha", EXPECTED_HEAD,
            "--kind", "rebase",
            "--force-with-lease",
            "--server-url", "https://github.example",
        ]
    ) == 0
    assert seen["kwargs"] == {
        "token": "token",
        "kind": "rebase",
        "force_with_lease": True,
        "server_url": "https://github.example",
    }
    assert json.loads(capsys.readouterr().out) == {
        "head_ref": "feature",
        "head_repository": "owner/repo",
        "mode": "direct",
        "pull_number": None,
        "url": None,
    }
