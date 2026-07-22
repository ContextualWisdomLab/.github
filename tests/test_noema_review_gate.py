import base64
import hashlib
import json
import sys

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import opencode_existing_approval_gate as approval_gate
from scripts.ci import opencode_review_normalize_output as normalizer


HEAD = "a" * 40
BASE_REF = "main"
BASE_SHA = "b" * 40
SOURCE_PATH = "src/app.py"
SOURCE_LINES = (b"def one():", b"    return 1")


@pytest.fixture(autouse=True)
def trusted_primary_approval_artifacts(tmp_path, monkeypatch):
    """Provide exact-head source and changed-file evidence to the shared gate."""
    runner_temp = tmp_path / "runner-temp"
    source_root = tmp_path / "source"
    source_path = source_root / SOURCE_PATH
    runner_temp.mkdir()
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"\n".join(SOURCE_LINES) + b"\n")
    changed_files = runner_temp / "opencode-changed-files.txt"
    changed_files.write_text(f"{SOURCE_PATH}\n", encoding="utf-8")
    manifest = runner_temp / "opencode-artifact-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "artifacts": {
                    changed_files.name: hashlib.sha256(
                        changed_files.read_bytes()
                    ).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(source_root))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    monkeypatch.setenv("OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION", "true")
    monkeypatch.setenv(
        "OPENCODE_ARTIFACT_MANIFEST_SHA256",
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    cached_helpers = (
        normalizer.trusted_artifact_manifest,
        normalizer.current_changed_files,
        normalizer.trusted_execution_receipts,
    )
    for helper in cached_helpers:
        if hasattr(helper, "cache_clear"):
            helper.cache_clear()
    yield
    for helper in cached_helpers:
        if hasattr(helper, "cache_clear"):
            helper.cache_clear()


def identity_body(marker: str = "Result: APPROVE", *, head: str = HEAD) -> str:
    """Build review text bound to the default test PR identity."""
    return "\n".join(
        (
            marker,
            f"- Base ref: `{BASE_REF}`",
            f"- Base SHA: `{BASE_SHA}`",
            f"- Head SHA: `{head}`",
        )
    )


def valid_primary_body(*, head: str = HEAD) -> str:
    """Build a primary review accepted by the shared strict approval gate."""
    evidence = {
        "status": "passed",
        "probes": [
            {
                "path": SOURCE_PATH,
                "line": line,
                "hypothesis": f"Approval bypass hypothesis {line}.",
                "attack_or_counterexample": f"Forged review evidence variant {line}.",
                "evidence": (
                    f"Source trace at {SOURCE_PATH}:{line} rejected the variant. "
                    "source-line-sha256=" + hashlib.sha256(source_line).hexdigest()
                ),
                "outcome": "falsified",
            }
            for line, source_line in enumerate(SOURCE_LINES, start=1)
        ],
        "residual_risk": "Repository branch policy remains externally enforced.",
    }
    control = {
        "head_sha": head,
        "run_id": "123",
        "run_attempt": "2",
        "result": "APPROVE",
        "reason": "No blocking findings.",
        "summary": "Exact-head evidence passed adversarial validation.",
        "adversarial_validation": evidence,
        "findings": [],
    }
    return "\n".join(
        (
            approval_gate.PRIMARY_APPROVAL_MARKER,
            "",
            "<!-- opencode-review-control-v1",
            json.dumps(control),
            "-->",
            "",
            "## Adversarial validation",
            "```json",
            json.dumps(evidence),
            "```",
            "",
            "- Result: APPROVE",
            f"- Base ref: `{BASE_REF}`",
            f"- Base SHA: `{BASE_SHA}`",
            f"- Head SHA: `{head}`",
            "- Workflow run: 123",
            "- Workflow attempt: 2",
        )
    )


def fake_secret(*parts: str) -> str:
    return "".join(parts)


def make_pr(**overrides):
    """Build a minimal pull request payload for Noema tests."""
    value = {
        "number": 7,
        "title": "Noema",
        "body": "",
        "isDraft": False,
        "baseRefName": BASE_REF,
        "baseRefOid": BASE_SHA,
        "headRefOid": HEAD,
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": []}},
    }
    value.update(overrides)
    return value


def review(state="APPROVED", commit=HEAD, login="opencode-agent", body=None):
    """Build a minimal review node for Noema tests."""
    return {
        "state": state,
        "body": valid_primary_body(head=commit) if body is None else body,
        "author": {"login": login},
        "commit": {"oid": commit},
    }


def test_run_split_repo_graphql_and_fetch_pr(monkeypatch):
    assert noema.run([sys.executable, "-c", "print('ok')"]).strip() == "ok"
    with pytest.raises(TypeError):
        noema.run("echo unsafe")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        noema.run([sys.executable, "-c", "import sys; sys.exit(5)"])

    assert noema.split_repo("owner/repo") == ("owner", "repo")

def test_scrub_sensitive_data():
    assert noema.scrub_sensitive_data(None) is None
    assert noema.scrub_sensitive_data("") == ""
    assert noema.scrub_sensitive_data("ok") == "ok"
    assert noema.scrub_sensitive_data("Bearer abcdef123") == "Bearer ***"
    assert noema.scrub_sensitive_data("TOKEN xyz_987") == "TOKEN ***"
    assert noema.scrub_sensitive_data(fake_secret("github_", "pat_", "123456789")) == "***"
    assert noema.scrub_sensitive_data(fake_secret("gh", "p_", "12345")) == "***"
    assert noema.scrub_sensitive_data("sk-abc-123_456") == "***"
    assert noema.scrub_sensitive_data("xoxb-1234-5678") == "***"
    assert noema.scrub_sensitive_data("AKIA1234567890ABCDEF") == "***"
    assert noema.scrub_sensitive_data("api_key=12345") == "api_key=***"
    assert noema.scrub_sensitive_data("client_secret='abc'") == "client_secret=***"
    assert noema.scrub_sensitive_data("password: xyz") == "password: ***"


def test_scrub_sensitive_data_authorization_headers():
    assert noema.scrub_sensitive_data("Authorization: Basic dXNlcjpwYXNz") == "Authorization: Basic ***"
    assert noema.scrub_sensitive_data("Proxy-Authorization: Basic dXNlcjpwYXNz") == "Proxy-Authorization: Basic ***"
    assert noema.scrub_sensitive_data("authorization: bearer xyz") == "authorization: bearer ***"


def test_split_repo_and_graphql(monkeypatch):
    with pytest.raises(ValueError):
        noema.split_repo("owner")
    with pytest.raises(ValueError):
        noema.split_repo("/repo")

    calls = []

    def fake_run(args, stdin=None):
        calls.append((args, stdin))
        return '{"data":{"repository":{"pullRequest":{"number":7}}}}'

    monkeypatch.setattr(noema, "run", fake_run)
    assert noema.graphql("query", owner="owner", number=7)["data"]["repository"]["pullRequest"]["number"] == 7
    assert "-f" in calls[0][0]
    assert "-F" in calls[0][0]
    assert noema.fetch_pr("owner/repo", 7) == {"number": 7}

    monkeypatch.setattr(noema, "graphql", lambda *args, **kwargs: {"data": {"repository": {"pullRequest": None}}})
    with pytest.raises(RuntimeError, match="was not found"):
        noema.fetch_pr("owner/repo", 8)


def test_review_state_helpers_cover_current_head_logic():
    marker_body = valid_primary_body()
    current = review(body=marker_body)
    old = review(commit="old", body=marker_body)
    pr = make_pr(reviews={"nodes": [old, current]})

    assert noema.review_author(current) == "opencode-agent"
    assert noema.review_author({}) == ""
    assert noema.review_commit(current) == HEAD
    assert noema.review_commit({}) == ""
    assert noema.current_primary_approval(pr) == current
    marker_only = review(
        body=identity_body(approval_gate.PRIMARY_APPROVAL_MARKER)
    )
    assert (
        noema.current_primary_approval(
            make_pr(reviews={"nodes": [marker_only]})
        )
        is None
    )
    assert (
        noema.current_primary_approval(
            make_pr(baseRefName="release", reviews={"nodes": [current]})
        )
        is None
    )
    assert (
        noema.current_primary_approval(
            make_pr(baseRefOid="c" * 40, reviews={"nodes": [current]})
        )
        is None
    )
    assert noema.current_primary_approval(make_pr(reviews={"nodes": [old]})) is None
    assert (
        noema.current_primary_approval(
            make_pr(reviews={"nodes": [review("COMMENTED", body=marker_body)]})
        )
        is None
    )
    assert (
        noema.current_primary_approval(
            make_pr(reviews={"nodes": [review(login="human", body=marker_body)]})
        )
        is None
    )
    assert (
        noema.current_primary_approval(
            make_pr(
                reviews={
                    "nodes": [review(login="github-actions[bot]", body=marker_body)]
                }
            )
        )
        is None
    )
    assert noema.has_current_changes_requested(
        make_pr(reviews={"nodes": [review("CHANGES_REQUESTED")]})
    )
    assert not noema.has_current_changes_requested(
        make_pr(reviews={"nodes": [review("CHANGES_REQUESTED", commit="old")]})
    )
    assert noema.has_unresolved_threads(
        make_pr(reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]})
    )
    assert not noema.has_unresolved_threads(
        make_pr(reviewThreads={"nodes": [{"isResolved": False, "isOutdated": True}]})
    )


def test_review_state_helpers_reject_explicit_previous_head_evidence():
    current_head = "a" * 40
    previous_head = "b" * 40
    approval_marker = "Result: APPROVE"
    stale_approval = review(
        commit=current_head,
        body=f"{approval_marker}\n\n- Head SHA: `{previous_head}`",
    )
    exact_approval = review(
        commit=current_head,
        body=valid_primary_body(head=current_head),
    )
    stale_change_request = review(
        "CHANGES_REQUESTED",
        commit=current_head,
        body=f"Result: REQUEST_CHANGES\n\n- Head SHA: `{previous_head}`",
    )

    assert noema.current_primary_approval(
        make_pr(headRefOid=current_head, reviews={"nodes": [stale_approval]})
    ) is None
    assert noema.current_primary_approval(
        make_pr(headRefOid=current_head, reviews={"nodes": [exact_approval]})
    ) == exact_approval
    assert not noema.has_current_changes_requested(
        make_pr(headRefOid=current_head, reviews={"nodes": [stale_change_request]})
    )


def test_review_identity_ignores_incidental_or_quoted_labels():
    """Only canonical identity bullets can bind a review to a pull request."""
    previous_head = "b" * 40
    body = "\n".join(
        (
            valid_primary_body(),
            "",
            f"Diagnostic prose mentions Head SHA: `{previous_head}`.",
            "> - Base ref: `quoted-branch`",
            f"> - Base SHA: `{previous_head}`",
        )
    )
    exact_approval = review(body=body)

    assert noema.review_matches_current_head(
        exact_approval,
        make_pr(),
        require_base_identity=True,
    )


def test_check_helpers_and_existing_noema_review():
    status_context = {"__typename": "StatusContext", "context": "ci", "state": "FAILURE"}
    check_run = {
        "__typename": "CheckRun",
        "name": "build",
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
    }
    failed_run = {
        "__typename": "CheckRun",
        "name": "lint",
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
    }
    running_run = {
        "__typename": "CheckRun",
        "name": "slow",
        "status": "IN_PROGRESS",
        "conclusion": None,
        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
    }

    assert noema.check_label(status_context) == "ci"
    assert noema.check_label(check_run) == "CI / build"
    assert not noema.existing_noema_review(make_pr(), "")
    blockers = noema.blocking_checks(
        make_pr(
            statusCheckRollup={
                "contexts": {
                    "nodes": [
                        status_context,
                        check_run,
                        failed_run,
                        running_run,
                        {"__typename": "CheckRun", "name": "Required Noema Review", "status": "IN_PROGRESS"},
                    ]
                }
            }
        )
    )
    assert "ci: FAILURE" in blockers
    assert "CI / lint: FAILURE" in blockers
    assert "CI / slow: IN_PROGRESS" in blockers
    assert noema.existing_noema_review(
        make_pr(
            reviews={
                "nodes": [
                    review(
                        login="noema",
                        body=identity_body(
                            "<!-- noema-review-gate base_ref=main "
                            f"base_sha={BASE_SHA} head_sha={HEAD} -->"
                        ),
                    )
                ]
            }
        ),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(
            reviews={
                "nodes": [
                    review(
                        login="attacker",
                        body=identity_body("<!-- noema-review-gate -->"),
                    )
                ]
            }
        ),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="noema", body=identity_body())]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review("DISMISSED", login="noema")]}), "noema"
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(commit="old", login="noema")]}), "noema"
    )


def test_current_actor_fetch_diff_and_json_extraction(monkeypatch):
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "noema\n")
    assert noema.current_actor() == "noema"
    monkeypatch.setattr(
        noema,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no gh")),
    )
    assert noema.current_actor() == ""

    monkeypatch.setattr(
        noema, "run", lambda *args, **kwargs: "x" * (noema.MAX_DIFF_CHARS + 5)
    )
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated
    assert len(diff) == noema.MAX_DIFF_CHARS

    assert noema.extract_json_object('{"decision":"approve"}') == {
        "decision": "approve"
    }
    assert noema.extract_json_object('prefix {"decision":"comment"} suffix') == {
        "decision": "comment"
    }
    with pytest.raises(RuntimeError, match="did not contain"):
        noema.extract_json_object("not-json")


def test_review_context_builders_include_codegraph_threads_and_files(
    monkeypatch, tmp_path
):
    assert noema.truncate_text("abc", 10) == "abc"
    assert "truncated 2 characters" in noema.truncate_text("abcdef", 4)
    assert "missing PR head SHA" in noema.changed_file_context("owner/repo", 7, "")

    original_fetch_paths = noema.fetch_changed_file_paths
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: [])
    assert "no changed files" in noema.changed_file_context("owner/repo", 7, "head")
    monkeypatch.setattr(noema, "fetch_changed_file_paths", original_fetch_paths)

    encoded = base64.b64encode(b"print('hello')\n").decode("ascii")
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        target = args[2]
        if target.endswith("/files"):
            return "src/a.py\nREADME.md\nempty.txt\n"
        if "contents/src/a.py" in target:
            return encoded
        if "contents/README.md" in target:
            raise RuntimeError("Command failed: token secret")
        if "contents/empty.txt" in target:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)
    codegraph_path = tmp_path / "codegraph.md"
    codegraph_path.write_text("call graph: src/a.py -> tests", encoding="utf-8")
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(codegraph_path))
    pr = make_pr(
        headRefOid="head sha",
        reviewThreads={
            "nodes": [
                {
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/a.py",
                    "line": 3,
                    "comments": {"nodes": [{"author": {"login": "reviewer"}, "body": "check call site"}]},
                },
                {
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "README.md",
                    "comments": {"nodes": []},
                },
            ]
        },
    )

    context = noema.build_review_context("owner/repo", 7, pr)

    assert "## CodeGraph context" in context
    assert "call graph: src/a.py -> tests" in context
    assert "Thread open at src/a.py:3" in context
    assert "reviewer: check call site" in context
    assert "### src/a.py" in context
    assert "print('hello')" in context
    assert "Unavailable from head content API" in context
    assert "No UTF-8 text content available" in context
    assert any("/files" in call[2] for call in calls)


def test_review_context_reports_omitted_files_and_missing_codegraph(monkeypatch, tmp_path):
    monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
    assert noema.load_codegraph_context() == ""

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(tmp_path / "missing.md"))
    assert "CodeGraph context unavailable" in noema.load_codegraph_context()

    paths = [f"src/file_{index}.py" for index in range(noema.MAX_CONTEXT_FILES + 1)]
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)
    monkeypatch.setattr(noema, "fetch_head_file_content", lambda repo, path, head_sha: "x")

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert "1 changed files omitted from context budget" in context


class FakeResponse:
    """Small response object for pinned HTTPS transport tests."""

    def __init__(self, payload, status=200, content_length=None):
        """Store a JSON-serializable response payload."""
        self.payload = payload
        self.status = status
        self.content_length = content_length

    def getheader(self, name):
        """Return an optional synthetic Content-Length header."""
        return self.content_length if name.lower() == "content-length" else None

    def read(self, amount=None):
        """Return the payload as encoded JSON bytes."""
        encoded = json.dumps(self.payload).encode("utf-8")
        return encoded if amount is None else encoded[:amount]


def test_call_llm_handles_configuration_and_verdicts(monkeypatch):
    pr = make_pr()
    monkeypatch.delenv("NOEMA_LLM_API_URL", raising=False)
    monkeypatch.delenv("NOEMA_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    with pytest.raises(ValueError, match="must use https://"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://llm.example.test/chat")
    with pytest.raises(ValueError, match="must use https://"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    response = {
        "value": FakeResponse(
            {"choices": [{"message": {"content": '{"decision":"approve","summary":"ok","findings":[]}'}}]}
        )
    }
    seen = {}

    class FakeConnection:
        def __init__(self, hostname, port, pinned_ip, *, timeout):
            seen.update(hostname=hostname, port=port, pinned_ip=pinned_ip, timeout=timeout)

        def request(self, method, target, *, body, headers):
            seen.update(
                method=method,
                target=target,
                body=json.loads(body.decode("utf-8")),
                headers=headers,
            )

        def getresponse(self):
            return response["value"]

        def close(self):
            seen["closed"] = True

    def public_dns(host, port, *args, **kwargs):
        return [
            (noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
            (noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
        ]

    monkeypatch.setattr(noema.socket, "getaddrinfo", public_dns)
    monkeypatch.setattr(noema, "PinnedHTTPSConnection", FakeConnection)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat;v=1?mode=review")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "review-model")
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", True, "extra review context")
    assert verdict["decision"] == "approve"
    assert seen["hostname"] == "llm.example.test"
    assert seen["port"] == 443
    assert seen["pinned_ip"] == "8.8.8.8"
    assert seen["target"] == "/chat;v=1?mode=review"
    assert seen["headers"]["authorization"] == "Bearer secret"
    assert seen["body"]["model"] == "review-model"
    assert "extra review context" in seen["body"]["messages"][1]["content"]
    assert seen["closed"] is True

    original_limit = noema.MAX_LLM_RESPONSE_BYTES
    monkeypatch.setattr(noema, "MAX_LLM_RESPONSE_BYTES", 8)
    response["value"] = FakeResponse({"oversized": "response"})
    with pytest.raises(RuntimeError, match="response exceeded the size limit"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)
    response["value"] = FakeResponse({}, content_length="9")
    with pytest.raises(RuntimeError, match="response exceeded the size limit"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)
    monkeypatch.setattr(noema, "MAX_LLM_RESPONSE_BYTES", original_limit)

    response["value"] = FakeResponse(
        {"choices": [{"message": {"content": '{"decision":"defer"}'}}]}
    )
    with pytest.raises(RuntimeError, match="unsupported decision"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    response["value"] = FakeResponse(
        {"choices": [{"message": {"content": '{"decision":"approve","summary":"ok","findings":[]}'}}]}
    )
    monkeypatch.setenv("NOEMA_LLM_API_URL", "HTTPS://llm.example.test/chat")
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://llm.example.test/chat")
    with pytest.raises(ValueError, match="must use https://"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://localhost/chat")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https:///chat")
    with pytest.raises(ValueError, match="URL must have a valid hostname"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://169.254.169.254/chat")
    monkeypatch.setattr(
        noema.socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))
        ],
    )
    with pytest.raises(ValueError, match="non-public IP"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://unresolved.example.com/chat")
    monkeypatch.setattr(
        noema.socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(noema.socket.gaierror("not found")),
    )
    with pytest.raises(ValueError, match="could not be resolved"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://weird-dns.example.com/chat")
    monkeypatch.setattr(
        noema.socket,
        "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("not_an_ip", port))
        ],
    )
    with pytest.raises(ValueError, match="invalid IP"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setattr(noema.socket, "getaddrinfo", lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="no addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setattr(noema.socket, "getaddrinfo", public_dns)
    for unsafe_url, message in (
        ("https://user:password@llm.example.test/chat", "user information"),
        ("https://llm.example.test/chat#fragment", "fragment"),
        ("https://llm.example.test:bad/chat", "invalid port"),
    ):
        monkeypatch.setenv("NOEMA_LLM_API_URL", unsafe_url)
        with pytest.raises(ValueError, match=message):
            noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    response["value"] = FakeResponse({"error": "redirect denied"}, status=302)
    with pytest.raises(RuntimeError, match="HTTP 302"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)


def test_pinned_https_connection_uses_numeric_peer_and_original_sni(monkeypatch):
    """The transport must never resolve the validated hostname a second time."""
    seen = {}

    class FakeSocket:
        def setsockopt(self, *args):
            seen["setsockopt"] = args

        def close(self):
            seen["closed"] = True

    fake_socket = FakeSocket()

    def fake_create_connection(address, timeout, source_address):
        seen.update(address=address, timeout=timeout, source_address=source_address)
        return fake_socket

    class FakeContext:
        def wrap_socket(self, sock, *, server_hostname):
            seen.update(wrapped_socket=sock, server_hostname=server_hostname)
            return sock

    monkeypatch.setattr(noema.socket, "create_connection", fake_create_connection)
    connection = noema.PinnedHTTPSConnection("llm.example.test", 443, "8.8.8.8", timeout=12)
    connection._context = FakeContext()
    connection.connect()
    connection.close()

    assert seen["address"] == ("8.8.8.8", 443)
    assert seen["server_hostname"] == "llm.example.test"
    assert seen["wrapped_socket"] is fake_socket
    assert seen["closed"] is True


def test_noema_redirect_handler_rejects_redirects():
    """Noema must not follow redirects after validating the initial URL."""
    handler = noema.NoRedirectHandler()
    request = noema.urllib.request.Request("https://llm.example.test/chat")

    with pytest.raises(noema.urllib.error.HTTPError):
        handler.redirect_request(
            request,
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="http://169.254.169.254/latest/meta-data/",
        )


def test_call_llm_rejects_control_character_scheme_evasion(monkeypatch):
    """A URL with an embedded tab is normalized by urlparse to an http scheme
    with a valid hostname, but its raw form does not start with http:// — the
    startswith guard must still reject it to prevent SSRF via control-character
    scheme evasion."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http\t://sneaky.example.com/chat")

    import socket

    def raise_gaierror(host, port, *args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    with pytest.raises(ValueError, match="control characters"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)


def test_call_llm_rejects_non_http_parsed_scheme(monkeypatch):
    """Keep the parsed-scheme SSRF guard covered as defense in depth."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    parsed = noema.urllib.parse.ParseResult("file", "llm.example.test", "/chat", "", "", "")
    monkeypatch.setattr(noema.urllib.parse, "urlparse", lambda _: parsed)

    with pytest.raises(ValueError, match="https scheme"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)


def test_format_findings_and_submit_review(monkeypatch):
    findings = noema.format_findings(
        [
            {"severity": "high", "file": "a.py", "line": 3, "message": "bad"},
            {"severity": "low", "file": "b.py", "line": 0, "message": "note"},
            "skip",
            {"message": ""},
        ]
    )
    assert findings == ["- [high] a.py:3: bad", "- [low] b.py: note"]

    calls = []
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "oidc")
    monkeypatch.setattr(
        noema,
        "run",
        lambda args, stdin=None: calls.append((args, json.loads(stdin))) or "",
    )
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    noema.submit_review(
        "owner/repo",
        7,
        make_pr(),
        "noema",
        {
            "decision": "request_changes",
            "summary": "fix it",
            "findings": [{"file": "a.py", "line": 1, "message": "bad"}],
        },
    )
    payload = calls[0][1]
    assert payload["event"] == "REQUEST_CHANGES"
    assert payload["commit_id"] == HEAD
    assert "Noema LLM review" in payload["body"]
    assert f"- Base ref: `{BASE_REF}`" in payload["body"]
    assert f"- Base SHA: `{BASE_SHA}`" in payload["body"]
    assert "oidc" in payload["body"]

    calls.clear()
    noema.submit_review("owner/repo", 7, make_pr(), "", {"decision": "comment"})
    assert calls[0][1]["event"] == "COMMENT"
    assert "No blocking findings" in calls[0][1]["body"]

    monkeypatch.setattr(
        noema,
        "fetch_pr",
        lambda repo, number: make_pr(baseRefName="release"),
    )
    with pytest.raises(RuntimeError, match="live base/head identity changed"):
        noema.submit_review(
            "owner/repo", 7, make_pr(), "noema", {"decision": "approve"}
        )


def test_inspect_and_review_skip_paths(monkeypatch):
    marker_body = valid_primary_body()
    clean_pr = make_pr(reviews={"nodes": [review(body=marker_body)]})
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok", "findings": []})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert calls

    existing_review = (
        make_pr(
            reviews={
                "nodes": [
                    review(
                        login="noema",
                        body=identity_body("<!-- noema-review-gate -->"),
                    )
                ]
            }
        ),
        "noema",
    )
    calls.clear()
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: existing_review[0])
    monkeypatch.setattr(noema, "current_actor", lambda: existing_review[1])
    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert calls == []

    cases = [
        (make_pr(), "noema", "primary OpenCode approval"),
        (make_pr(isDraft=True), "noema", "draft pull request"),
        (
            make_pr(
                reviews={"nodes": [review(body=marker_body)]},
                reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]},
            ),
            "noema",
            "unresolved review threads",
        ),
        (
            make_pr(
                reviews={
                    "nodes": [review("CHANGES_REQUESTED"), review(body=marker_body)]
                }
            ),
            "noema",
            "request-changes review",
        ),
        (
            make_pr(
                reviews={"nodes": [review(body=marker_body)]},
                statusCheckRollup={
                    "contexts": {
                        "nodes": [
                            {
                                "__typename": "StatusContext",
                                "context": "ci",
                                "state": "FAILURE",
                            }
                        ]
                    }
                },
            ),
            "noema",
            "Blocking checks remain",
        ),
        (clean_pr, "opencode-agent", "independent Noema reviewer"),
        (clean_pr, "", "credential identity"),
    ]
    for pr, actor, message in cases:
        calls.clear()
        monkeypatch.setattr(noema, "fetch_pr", lambda repo, number, pr=pr: pr)
        monkeypatch.setattr(noema, "current_actor", lambda actor=actor: actor)
        with pytest.raises(RuntimeError, match=message):
            noema.inspect_and_review("owner/repo", 7)
        assert calls == []


def test_parse_args_and_main(monkeypatch):
    parsed = noema.parse_args(["--repo", "owner/repo", "--pr-number", "9"])
    assert parsed.repo == "owner/repo"
    assert parsed.pr_number == 9

    seen = []
    monkeypatch.setattr(
        noema,
        "inspect_and_review",
        lambda repo, number: seen.append((repo, number)) or 0,
    )
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9"]) == 0
    assert seen == [("owner/repo", 9)]

    with pytest.raises(SystemExit, match="--pr-number must be positive"):
        noema.main(["--repo", "owner/repo", "--pr-number", "0"])
