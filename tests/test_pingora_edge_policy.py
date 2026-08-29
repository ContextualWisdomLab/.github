"""Regression tests for the organization-wide Pingora edge policy."""

from __future__ import annotations

import base64
import importlib.util
import sys
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "ci" / "pingora_edge_policy.py"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "pingora_policy_samples.txt"
SPEC = importlib.util.spec_from_file_location("pingora_edge_policy", MODULE_PATH)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def fixture_text() -> str:
    """Return the dedicated source sample used to exercise denied runtime forms."""
    return FIXTURE_PATH.read_text(encoding="utf-8")


def encoded_file(content: str, *, size: int | None = None, kind: str = "file", encoding: str = "base64") -> dict[str, object]:
    """Build one GitHub Contents API response."""

    raw = content.encode()
    return {
        "type": kind,
        "encoding": encoding,
        "size": len(raw) if size is None else size,
        "content": base64.b64encode(raw).decode(),
    }


def test_scan_content_rejects_runtime_paths_and_every_denied_runtime_form() -> None:
    """Runtime filenames and all supported active Nginx forms fail closed."""

    content = fixture_text()
    violations = policy.scan_content("infra/nginx/nginx.conf", content)
    rules = {item.rule for item in violations}
    assert rules == {
        "nginx_runtime_artifact",
        "nginx_container_image",
        "nginx_ingress_controller",
        "nginx_runtime_command",
        "nginx_runtime_path",
        "nginx_package_install",
    }
    assert all(item.line >= 1 and item.excerpt for item in violations)


def test_scan_content_allows_prose_license_and_source_negative_fixtures() -> None:
    """Policy prose, license text, and scanner source fixtures can name Nginx."""

    sample = fixture_text()
    assert policy.scan_content("docs/migration.md", sample) == ()
    assert policy.scan_content("COPYING", sample) == ()
    assert policy.scan_content("scripts/ci/pingora_edge_policy.py", sample) == ()
    assert policy.scan_content("tests/fixtures/policy_samples.py", sample) == ()
    assert policy.scan_content("tests/fixtures/negative_fixture.rs", sample) == ()
    assert policy.scan_content("deploy/fixtures/runtime.yaml", sample)
    assert policy.scan_content(
        "deploy/monitoring.yaml", "image: nginx/nginx-prometheus-exporter:1.0\n"
    ) == ()
    assert policy.scan_content(
        "deploy/ingress.yaml", "image: nginx/nginx-ingress:1.11\n"
    )


def test_nested_documentation_path_allows_prose_samples() -> None:
    """Documentation directories remain exempt when nested below a package."""

    assert policy.scan_content("packages/component/docs/migration.md", fixture_text()) == ()


@pytest.mark.parametrize("directory", ["testing", "contests", "assert", "my_tests"])
def test_scan_content_does_not_treat_test_name_substrings_as_fixtures(
    directory: str,
) -> None:
    """Only exact test directories are fixture boundaries for active content."""

    violations = policy.scan_content(
        f"{directory}/runtime.py",
        "FROM nginx:1.27-alpine\n",
    )

    assert [item.rule for item in violations] == ["nginx_container_image"]


def test_runtime_path_rule_covers_script_and_config_shapes() -> None:
    """Active Nginx filenames are blocked without relying on their contents."""

    assert policy._runtime_path_rule("tests/live/nginx.conf") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("ops/nginx-backup.sh") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("infra/nginx/default.yaml") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("config/nginx/default.conf") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("config/nginx.service") == "nginx_runtime_artifact"
    assert policy._runtime_path_rule("docs/nginx-history.md") is None


def test_needs_content_scan_is_delta_bounded() -> None:
    """Removed/prose files skip, while bounded runtime candidates always scan."""

    changed = policy.ChangedFile
    assert not policy._needs_content_scan(changed("Dockerfile", "removed", "+FROM nginx"))
    assert not policy._needs_content_scan(changed("README.md", "modified", "+nginx"))
    assert policy._needs_content_scan(changed("Dockerfile", "modified", "-FROM nginx\n+FROM scratch"))
    assert policy._needs_content_scan(changed("config/runtime.txt", "modified", "+FROM nginx"))
    assert policy._needs_content_scan(changed("infra/nginx/default.yaml", "modified", "+server: edge"))
    assert policy._needs_content_scan(changed("kubernetes/ingress.yaml", "modified", "+metadata: edge"))
    assert policy._needs_content_scan(changed("ops/edge.yaml", "modified", "+metadata: edge"))
    assert policy._needs_content_scan(changed("infra/deployment.yaml", "modified", "+image: app"))
    assert policy._needs_content_scan(changed("manifests/ingress.yaml", "modified", "+metadata: edge"))
    assert policy._needs_content_scan(changed("config/runtime.conf", "modified", "+upstream nginx"))
    assert policy._needs_content_scan(
        changed("config/runtime.conf", "modified", "", patch_available=False)
    )
    assert policy._needs_content_scan(changed("config/runtime.conf", "modified", "+upstream app"))
    assert policy._needs_content_scan(changed("src/runtime.go", "modified", "+exec nginx"))
    assert not policy._needs_content_scan(changed("src/runtime.go", "modified", "+exec pingora"))


def test_active_test_source_is_scanned_while_dedicated_fixtures_are_exempt() -> None:
    """Executable test helpers remain candidates; only explicit fixtures are exempt."""

    violations = policy.scan_content("tests/e2e/start_nginx.py", "systemctl restart nginx\n")
    assert [item.rule for item in violations] == ["nginx_runtime_command"]


def test_source_identifier_is_not_an_nginx_command() -> None:
    """A source-language function name is not an executable shell launch."""

    assert policy.scan_content("src/runtime.py", "nginx()\n") == ()


def test_sudo_options_are_supported_for_runtime_commands_and_packages() -> None:
    """Bounded sudo flags cannot hide prohibited Nginx operations."""

    violations = policy.scan_content(
        "src/runtime.sh", "sudo -n nginx -s reload\nsudo -n apt-get install nginx\n"
    )
    assert {item.rule for item in violations} == {
        "nginx_runtime_command",
        "nginx_package_install",
    }


def test_sudo_argument_options_do_not_reinterpret_their_values() -> None:
    """Sudo user values do not become false Nginx commands."""

    violations = policy.scan_content(
        "src/runtime.sh",
        "sudo -u nginx php-fpm\nsudo -u root nginx -s reload\n"
        "sudo --user root apt-get install nginx\n",
    )
    assert {item.rule for item in violations} == {
        "nginx_runtime_command",
        "nginx_package_install",
    }


def test_untrusted_document_suffix_does_not_bypass_runtime_scan() -> None:
    """A runtime-looking file cannot evade policy checks by using a prose suffix."""

    violations = policy.scan_content("config/runtime.txt", "FROM nginx:1.27-alpine\n")
    assert [item.rule for item in violations] == ["nginx_container_image"]


def test_evaluate_pull_request_reads_pagination_and_final_content() -> None:
    """The checker uses every file page and scans final head content, not removed lines."""

    calls: list[str] = []
    first_page = [
        {"filename": f"docs/file-{index}.md", "status": "modified", "patch": "+Nginx"}
        for index in range(100)
    ]
    second_page = [
        {"filename": "Dockerfile", "status": "modified", "patch": "-FROM nginx\n+FROM scratch"},
        {"filename": "old/nginx.conf", "status": "removed", "patch": "-server {}"},
        {"filename": "deploy/proxy.yaml", "status": "modified"},
    ]

    def opener(url: str, token: str) -> object:
        calls.append(url)
        assert token == "token"
        if url.endswith("page=1"):
            return first_page
        if url.endswith("page=2"):
            return second_page
        if "/contents/Dockerfile" in url:
            return encoded_file("FROM scratch\n")
        if "/contents/deploy/proxy.yaml" in url:
            return encoded_file("image: cwl-pingora-proxy:0.1.0\n")
        raise AssertionError(url)

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test/",
        repository="ContextualWisdomLab/example",
        pull_request=7,
        head_sha="a" * 40,
        event_action="synchronize",
        token="token",
        opener=opener,
    )
    assert result == ()
    assert any("page=2" in url for url in calls)
    assert all("old/nginx.conf" not in url for url in calls)


def test_evaluate_pull_request_reports_final_runtime_violation() -> None:
    """A changed active runtime image is rejected from final head content."""

    def opener(url: str, _token: str) -> object:
        if "/pulls/9/files" in url:
            return [{"filename": "docker-compose.yml", "status": "modified", "patch": "+image: nginx"}]
        return encoded_file("services:\n  edge:\n    image: nginx:1.27-alpine\n")

    result = policy.evaluate_pull_request(
        api_url="https://api.github.test",
        repository="ContextualWisdomLab/example",
        pull_request=9,
        head_sha="b" * 40,
        event_action="opened",
        token="token",
        opener=opener,
    )
    assert [item.rule for item in result] == ["nginx_container_image"]


def test_closed_event_skips_without_credentials_or_identity_validation() -> None:
    """Closed-event cleanup remains a no-op for the required-workflow context."""

    assert policy.evaluate_pull_request(
        api_url="x",
        repository="bad repo",
        pull_request=0,
        head_sha="bad",
        event_action="closed",
        token="",
        opener=lambda _url, _token: pytest.fail("must not open"),
    ) == ()


@pytest.mark.parametrize(
    ("repository", "pull_request", "head_sha", "token", "message"),
    [
        ("bad repo", 1, "a" * 40, "x", "Repository identity"),
        ("a/b", 0, "a" * 40, "x", "must be positive"),
        ("a/b", 1, "bad", "x", "head SHA"),
        ("a/b", 1, "a" * 40, "", "GITHUB_TOKEN"),
    ],
)
def test_evaluate_pull_request_rejects_invalid_authority(
    repository: str, pull_request: int, head_sha: str, token: str, message: str
) -> None:
    """Malformed authority and absent credentials fail before network access."""

    with pytest.raises(policy.PolicyError, match=message):
        policy.evaluate_pull_request(
            api_url="x",
            repository=repository,
            pull_request=pull_request,
            head_sha=head_sha,
            event_action="opened",
            token=token,
            opener=lambda _url, _token: pytest.fail("must not open"),
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "not a JSON array"),
        (["bad"], "entry is not an object"),
        ([{"filename": "", "status": "modified", "patch": ""}], "invalid bounded fields"),
    ],
)
def test_changed_file_evidence_shape_is_fail_closed(payload: object, message: str) -> None:
    """Malformed changed-file API shapes fail closed."""

    with pytest.raises(policy.PolicyError, match=message):
        policy._load_changed_files("api", "a/b", 1, "x", lambda _url, _token: payload)


def test_changed_file_pagination_bound_is_fail_closed() -> None:
    """More than 3,000 changed files cannot silently truncate policy evidence."""

    page = [{"filename": f"f-{index}", "status": "modified", "patch": ""} for index in range(100)]
    with pytest.raises(policy.PolicyError, match="3,000"):
        policy._load_changed_files("api", "a/b", 1, "x", lambda _url, _token: page)


def test_changed_file_pagination_accepts_the_inclusive_bound() -> None:
    """Exactly 3,000 changed files are accepted only after an empty next page."""

    page = [
        {"filename": f"f-{index}", "status": "modified", "patch": ""}
        for index in range(100)
    ]
    calls: list[str] = []

    def opener(url: str, _token: str) -> object:
        calls.append(url)
        return page if "page=31" not in url else []

    files = policy._load_changed_files("api", "a/b", 1, "x", opener)
    assert len(files) == 3_000
    assert calls[-1].endswith("page=31")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "not an object"),
        ({"type": "symlink", "encoding": "base64", "size": 0, "content": ""}, "not a regular"),
        ({"type": "file", "encoding": "base64", "size": policy.MAX_FILE_BYTES + 1, "content": ""}, "size contract"),
        ({"type": "file", "encoding": "base64", "size": 1, "content": "!"}, "invalid base64"),
        ({"type": "file", "encoding": "base64", "size": 2, "content": base64.b64encode(b"x").decode()}, "size mismatch"),
        ({"type": "file", "encoding": "base64", "size": 1, "content": base64.b64encode(b"\xff").decode()}, "not valid UTF-8"),
    ],
)
def test_file_content_evidence_is_fail_closed(payload: object, message: str) -> None:
    """Unbounded, nonregular, corrupt, or binary runtime content is rejected."""

    with pytest.raises(policy.PolicyError, match=message):
        policy._load_file_content("api", "a/b", "x y", "a" * 40, "x", lambda url, _token: payload)


def test_file_content_loader_quotes_paths() -> None:
    """Contents API paths are percent-encoded without losing path separators."""

    seen: list[str] = []

    def opener(url: str, _token: str) -> object:
        seen.append(url)
        return encoded_file("ok")

    assert policy._load_file_content("api", "a/b", "dir/a b.conf", "a" * 40, "x", opener) == "ok"
    assert "dir/a%20b.conf" in seen[0]


def test_file_content_loader_accepts_wrapped_base64_content() -> None:
    """GitHub's line-wrapped Contents API base64 remains valid evidence."""

    payload = encoded_file("FROM scratch\n")
    encoded = str(payload["content"])
    payload["content"] = "\n".join(encoded[index : index + 4] for index in range(0, len(encoded), 4))

    assert policy._load_file_content(
        "api", "a/b", "Dockerfile", "a" * 40, "x", lambda _url, _token: payload
    ) == "FROM scratch\n"


class FakeResponse:
    """Context-managed bounded response for direct opener tests."""

    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.payload


def test_github_open_json_accepts_valid_bounded_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default opener parses bounded GitHub JSON."""

    monkeypatch.setattr(policy.github_opener, "open", lambda _request, timeout: FakeResponse(b'{"ok": true}'))
    assert policy._github_open_json("https://api.github.com/repos/a/b", "token") == {"ok": True}


@pytest.mark.parametrize("exc", [URLError("dns"), TimeoutError(), HTTPError("x", 500, "bad", {}, BytesIO())])
def test_github_open_json_sanitizes_transport_failures(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Network failures preserve only their stable class, never response text."""

    def fail(_request: object, timeout: int) -> object:
        assert timeout == 30
        raise exc

    monkeypatch.setattr(policy.github_opener, "open", fail)
    with pytest.raises(policy.PolicyError, match=type(exc).__name__):
        policy._github_open_json("https://api.github.com/repos/a/b", "token")


def test_github_open_json_rejects_oversized_and_malformed_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST evidence must remain one bounded valid JSON document."""

    monkeypatch.setattr(policy.github_opener, "open", lambda _request, timeout: FakeResponse(b"x" * (policy.MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(policy.PolicyError, match="bounded response size"):
        policy._github_open_json("https://api.github.com/repos/a/b", "token")
    monkeypatch.setattr(policy.github_opener, "open", lambda _request, timeout: FakeResponse(b"not-json"))
    with pytest.raises(policy.PolicyError, match="malformed JSON"):
        policy._github_open_json("https://api.github.com/repos/a/b", "token")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/a/b",
        "https://evil.example/repos/a/b",
        "https://user@api.github.com/repos/a/b",
        "https://api.github.com:443/repos/a/b",
        "https://api.github.com/user",
        "https://api.github.com/repos/a/b#fragment",
    ],
)
def test_github_open_json_rejects_nonapproved_origins(url: str) -> None:
    """Evidence collection cannot be redirected to attacker-controlled origins."""

    with pytest.raises(policy.PolicyError, match="approved origin"):
        policy._github_open_json(url, "token")


def test_github_opener_never_constructs_redirect_requests() -> None:
    """The policy opener refuses redirects rather than changing API origins."""

    assert policy.NoRedirectHandler().redirect_request(None, None, 302, "Found", {}, "https://evil.example") is None


def test_annotation_escapes_workflow_command_fields() -> None:
    """Workflow annotations cannot be broken by path or excerpt control syntax."""

    annotation = policy._annotation(policy.Violation("a,b%\n", "rule", 2, "bad%\ntext"))
    assert annotation.startswith("::error file=a%2Cb%25%0A,line=2::")
    assert "bad%25%0Atext" in annotation


def test_main_returns_pass_reject_and_evidence_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI exposes distinct success, policy rejection, and evidence-error statuses."""

    base_args = ["--repository", "a/b", "--pull-request", "1", "--head-sha", "a" * 40, "--event-action", "opened"]
    monkeypatch.setattr(policy, "evaluate_pull_request", lambda **_kwargs: ())
    assert policy.main(base_args, {"GITHUB_TOKEN": "x"}) == 0
    assert "passed" in capsys.readouterr().out

    violation = policy.Violation("Dockerfile", "nginx_container_image", 1, "FROM nginx")
    monkeypatch.setattr(policy, "evaluate_pull_request", lambda **_kwargs: (violation,))
    assert policy.main(base_args, {"GITHUB_TOKEN": "x"}) == 1
    assert "rejected 1" in capsys.readouterr().out

    def evidence_error(**_kwargs: object) -> tuple[object, ...]:
        raise policy.PolicyError("unavailable")

    monkeypatch.setattr(policy, "evaluate_pull_request", evidence_error)
    assert policy.main(base_args, {"GITHUB_TOKEN": "x"}) == 2
    assert "complete evidence" in capsys.readouterr().out


def test_build_parser_uses_pinned_public_api_origin() -> None:
    """The CLI defaults to the approved public GitHub API origin."""

    parser = policy.build_parser()
    args = parser.parse_args([
        "--repository", "a/b", "--pull-request", "1", "--head-sha", "a" * 40, "--event-action", "opened"
    ])
    assert args.api_url == "https://api.github.com"
