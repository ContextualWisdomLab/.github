"""Complete, fail-closed GHAS analyses traversal at the real HTTP boundary."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
import json
from urllib.parse import urlencode

import pytest

from scripts.ci import codeql_ghas_configuration_identity as identity


ENDPOINT = "https://api.github.com/repos/ContextualWisdomLab/example/code-scanning/analyses"


class _Page:
    """Serve one synthetic HTTP page without contacting GitHub."""

    def __init__(self, payload, link=""):
        """Keep the page body and its actual Link response header."""
        self.body = json.dumps(payload).encode()
        self.headers: dict[str, str] | Message = {"Link": link}

    def __enter__(self):
        """Open the response context."""
        return self

    def __exit__(self, *_args):
        """Close the response context without suppressing failures."""
        return None

    def read(self):
        """Return the serialized body."""
        return self.body


def _url(page=None, ref: str | None = "refs/heads/main", per_page=100):
    """Construct the documented analyses query, with an optional page number."""
    params = {"per_page": str(per_page), "tool_name": "CodeQL"}
    if ref:
        params["ref"] = ref
    if page is not None:
        params["page"] = str(page)
    return ENDPOINT + "?" + urlencode(params)


def test_separate_link_headers_keep_next_after_current_last(monkeypatch):
    """Every physical Link field contributes to the complete page traversal."""
    first = _Page([{"id": 1}])
    first.headers = Message()
    first.headers["Link"] = f'<{_url(1)}>; rel="last"'
    first.headers["link"] = f'<{_url(2)}>; rel="next"'
    pages = {_url(): first, _url(2): _Page([{"id": 2}])}
    calls = []

    def open_page(request, timeout):
        """Serve both pages and record their unchanged authenticated requests."""
        calls.append((request.full_url, request.get_header("Authorization"), timeout))
        return pages[request.full_url]

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    assert identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main") == [
        {"id": 1}, {"id": 2}
    ]
    assert calls == [(url, "Bearer opaque", 30) for url in pages]


@pytest.mark.parametrize("links", [
    [f'<{_url(2)}>; rel="next"', f'<{_url(2)}>; rel="next"'],
    [f'<{_url(2)}>; rel="next"', '<https://evil.example/analyses>; rel="next"'],
    [f'<{_url(1)}>; rel="last"', f'<{_url(1)}>; rel="last"'],
    [f'<{_url(2)}>; rel="next"', "garbage"],
    [f'<{_url(2)}>; rel="next"', ""],
    [f'<{_url(2)}>; rel="next"', f'<{_url(1)}>; rel="unknown"'],
    [f'<{_url(1)}>; rel="last"', '<https://evil.example/analyses>; rel="next"'],
    [f'<{_url(1)}>; rel="last"', f'<{_url(2, ref="refs/pull/7/head")}>; rel="next"'],
])
def test_separate_link_headers_reject_invalid_later_field_before_request(monkeypatch, links):
    """A later duplicate, malformed or unsafe field cannot hide behind the first."""
    response = _Page([{"id": 1}])
    response.headers = Message()
    for link in links:
        response.headers["Link"] = link
    calls = []

    def open_page(request, timeout):
        """Fail if any combined invalid header reaches another bearer request."""
        calls.append((request.full_url, request.get_header("Authorization")))
        assert len(calls) == 1, "invalid later Link field reached authenticated transport"
        return response

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert calls == [(_url(), "Bearer opaque")]


@pytest.mark.parametrize("header_type", ["message", "dict"])
@pytest.mark.parametrize("relation", [None, "", "last", "next"])
def test_message_and_dict_headers_preserve_absent_single_link_behavior(monkeypatch, header_type, relation):
    """Absent, empty and single Link fields preserve Message and dict compatibility."""
    response = _Page([{"id": 1}])
    response.headers = Message() if header_type == "message" else {}
    if relation is not None:
        response.headers["Link"] = (
            f'<{_url(2 if relation == "next" else 1)}>; rel="{relation}"' if relation else ""
        )
    terminal = _Page([{"id": 2}])
    terminal.headers = Message() if header_type == "message" else {}
    calls = []

    def open_page(request, timeout):
        """Serve a single optional next page without inventing extra headers."""
        calls.append((request.full_url, request.get_header("Authorization"), timeout))
        assert len(calls) <= (2 if relation == "next" else 1)
        return response if len(calls) == 1 else terminal

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    expected_urls = [_url(), _url(2)] if relation == "next" else [_url()]
    assert identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main") == [
        {"id": page} for page in range(1, len(expected_urls) + 1)
    ]
    assert calls == [(url, "Bearer opaque", 30) for url in expected_urls]


def test_complete_history_keeps_active_identity_after_first_hundred(monkeypatch):
    """A base identity on page three must still block an unpaired head."""
    base_sha, head_sha = "a" * 40, "b" * 40
    active = {"commit_sha": base_sha, "analysis_key": "active-workflow:analyze",
              "category": "/language:rust", "tool": {"name": "CodeQL"}}
    historical = [{"id": n, "commit_sha": "c" * 40} for n in range(200)]
    pages = {
        _url(): _Page(historical[:100], f'<{_url(2)}>; rel="next", <{_url(3)}>; rel="last"'),
        _url(2): _Page(historical[100:], f'<{_url(3)}>; rel="next", <{_url(1)}>; rel="prev"'),
        _url(3): _Page([active], f'<{_url(1)}>; rel="first", <{_url(2)}>; rel="prev"'),
    }
    calls = []

    def open_page(request, timeout):
        """Record every authenticated request and serve its exact page."""
        calls.append((request.full_url, request.get_header("Authorization"), timeout))
        return pages[request.full_url]

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    rows = identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert rows == historical + [active]
    assert identity.pairing_ready(rows, [], base_sha=base_sha, head_sha=head_sha, language="rust") == (
        False, [("active-workflow:analyze", "/language:rust")]
    )
    assert calls == [(url, "Bearer opaque", 30) for url in pages]


@pytest.mark.parametrize("target", [
    "https://evil.example/analyses?page=2",
    _url(2).replace("api.github.com", "api.github.com.evil.example"),
    _url(2).replace("https://", "http://"),
    _url(2).replace("api.github.com", "api.github.com:443"),
    _url(2).replace("api.github.com", "user@api.github.com"),
    _url(2) + "#fragment",
    _url(2).replace("/example/", "/other/"),
    _url(2).replace("/analyses?", "/alerts?"),
    _url(2, ref="refs/pull/7/head"),
    _url(2, ref=None),
    _url(2, per_page=50),
    _url(2).replace("tool_name=CodeQL", "tool_name=Semgrep"),
    _url(2) + "&ref=refs%2Fheads%2Fmain",
    _url(2) + "&extra=unreviewed",
    _url(2).replace("page=2", "page=4"),
    _url(2).replace("page=2", "page=0"),
    _url(2).replace("page=2", "page=two"),
    _url(2).replace("page=2", "page=02"),
    _url(2).replace("&page=2", ""),
    _url(2) + "&broken",
    "/repos/ContextualWisdomLab/example/code-scanning/analyses?page=2",
])
def test_next_link_cannot_change_authority_endpoint_or_query(monkeypatch, target):
    """Reject poisoned next URLs before constructing a second bearer request."""
    calls = []

    def open_page(request, timeout):
        """Refuse a second request even when its authority still appears valid."""
        calls.append((request.full_url, request.get_header("Authorization")))
        assert len(calls) == 1, "poisoned link reached authenticated transport"
        return _Page([{"id": 1}], f'<{target}>; rel="next"')

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert calls == [(_url(), "Bearer opaque")]


@pytest.mark.parametrize("link", [
    "garbage", '<missing-bracket; rel="next"',
    f'<{_url(2)}>; rel="next",',
    f'<{_url(2)}>; rel="next", <{_url(3)}>; rel="next"',
    f'<{_url(2)}>; rel="next"; rel="prev"',
    f'<{_url(2)}>; rel="unknown"',
])
def test_malformed_link_cannot_be_treated_as_complete(monkeypatch, link):
    """Malformed or ambiguous pagination never returns first-page evidence."""
    calls = []

    def open_page(request, timeout):
        """Bound the intentionally malformed chain so a regression cannot hang."""
        calls.append(request.full_url)
        assert len(calls) == 1, "malformed link was followed"
        return _Page([{"id": 1}], link)

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")


@pytest.mark.parametrize("terminal_page", [1, 2])
def test_last_beyond_current_without_next_never_returns_partial_evidence(monkeypatch, terminal_page):
    """A last relation advertising unseen pages cannot prove completeness."""
    calls = []

    def open_page(request, timeout):
        """Expose incomplete terminal evidence without following its last URL."""
        calls.append(request.full_url)
        assert len(calls) <= terminal_page, "incomplete terminal link was followed"
        relation = "next" if len(calls) < terminal_page else "last"
        target = _url(2) if relation == "next" else _url(3)
        return _Page([{"id": len(calls)}], f'<{target}>; rel="{relation}"')

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert calls == [_url(), _url(2)][:terminal_page]


@pytest.mark.parametrize("target", [
    _url(0), _url(1).replace("&page=1", "&page=one"),
    _url(1).replace("&page=1", ""), _url(1) + "&page=1", _url(1) + "&broken",
    _url(1, ref="refs/pull/7/head"), _url(1, per_page=50),
    _url(1).replace("tool_name=CodeQL", "tool_name=Semgrep"),
    _url(1).replace("/example/", "/other/"),
    _url(1).replace("/analyses?", "/alerts?"),
    _url(1).replace("api.github.com", "evil.example"),
])
def test_terminal_last_must_preserve_current_page_and_query(monkeypatch, target):
    """A terminal last URL must bind the same authority, endpoint and query."""
    calls = []

    def open_page(request, timeout):
        """Return an invalid terminal relation without permitting another request."""
        calls.append(request.full_url)
        assert len(calls) == 1, "terminal last URL was followed"
        return _Page([{"id": 1}], f'<{target}>; rel="last"')

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert calls == [_url()]


@pytest.mark.parametrize("terminal_page", [1, 2])
def test_terminal_last_equal_to_current_page_remains_supported(monkeypatch, terminal_page):
    """An explicit last relation naming the current page is complete evidence."""
    calls = []

    def open_page(request, timeout):
        """Serve sequential pages ending with a self-referential last relation."""
        calls.append(request.full_url)
        assert len(calls) <= terminal_page
        relation = "next" if len(calls) < terminal_page else "last"
        target = _url(2) if relation == "next" else _url(terminal_page)
        return _Page([{"id": len(calls)}], f'<{target}>; rel="{relation}"')

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    assert identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main") == [
        {"id": page} for page in range(1, terminal_page + 1)
    ]
    assert calls == [_url(), _url(2)][:terminal_page]


def test_cyclic_next_link_fails_before_repeated_request(monkeypatch):
    """A page-two link back to page one is not complete evidence or a retry."""
    calls = []

    def open_page(request, timeout):
        """Serve a cycle once, then expose any unsafe follow attempt."""
        calls.append(request.full_url)
        assert len(calls) <= 2, "cycle was followed"
        target = _url(2) if len(calls) == 1 else _url(1)
        return _Page([{"id": len(calls)}], f'<{target}>; rel="next"')

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert calls == [_url(), _url(2)]


@pytest.mark.parametrize("failure", ["http", "transport", "json", "utf8", "empty", "object"])
def test_later_page_failure_never_returns_partial_evidence(monkeypatch, failure):
    """Any second-page API/decoding/shape failure aborts the entire collection."""
    calls = []

    def open_page(request, timeout):
        """Serve a valid prefix before failing the final page."""
        calls.append(request.full_url)
        if len(calls) == 1:
            return _Page([{"id": 1}], f'<{_url(2)}>; rel="next"')
        if failure == "http":
            raise identity.urllib.error.HTTPError(request.full_url, 403, "denied", Message(), BytesIO(b"denied"))
        if failure == "transport":
            raise identity.urllib.error.URLError("offline")
        response = _Page({"error": "bad"} if failure == "object" else [])
        if failure in {"json", "utf8", "empty"}:
            response.body = {"json": b"[invalid", "utf8": b"\xff", "empty": b" "}[failure]
        return response

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert calls == [_url(), _url(2)]


def test_unbounded_chain_fails_at_documented_page_budget(monkeypatch):
    """One thousand pages is an independent literal bound, never a partial success."""
    assert identity.MAX_ANALYSES_PAGES == 1000
    calls = []

    def open_page(request, timeout):
        """Offer endless sequential pages while bounding this regression itself."""
        calls.append(request.full_url)
        assert len(calls) <= 1000, "unbounded chain reached transport"
        return _Page([{"id": len(calls)}], f'<{_url(len(calls) + 1)}>; rel="next"')

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError, match="page limit.*incomplete"):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert len(calls) == 1000


@pytest.mark.parametrize("per_page", [0, -1, 101, True, "100", 1.5])
def test_invalid_page_size_fails_before_transport(monkeypatch, per_page):
    """Only the API's integer range 1..100 can establish bounded page sizes."""
    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", lambda *a, **k: pytest.fail("invalid page size reached transport"))
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", per_page=per_page)


@pytest.mark.parametrize("repository", ["a/b/c", "a/../b", "a/b?ref=other", "a/b#fragment", "a/", "/b", "a/.", "a/.."])
def test_repository_cannot_inject_endpoint_or_query(monkeypatch, repository):
    """Bind the original endpoint to exactly two safe owner/name segments."""
    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", lambda *a, **k: pytest.fail("invalid repository reached transport"))
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses(repository, token="opaque")


@pytest.mark.parametrize("ref", [None, "refs/pull/82/head", "refs/heads/a,b&c"])
@pytest.mark.parametrize("per_page", [1, 100])
def test_valid_queries_and_terminal_empty_page_remain_supported(monkeypatch, ref, per_page):
    """Ref omission, escaping, query reordering and an empty JSON array are valid."""
    first = _url(ref=ref, per_page=per_page)
    # Query ordering is not identity, while the original decoded filters are.
    next_url = _url(2, ref=ref, per_page=per_page)
    path, query = next_url.split("?", 1)
    next_url = path + "?" + "&".join(reversed(query.split("&")))
    calls = []

    def open_page(request, timeout):
        """Return one row followed by an explicitly empty final JSON page."""
        calls.append(request.full_url)
        if len(calls) == 1:
            return _Page([{"id": 1}, "ignored-as-before"], f'<{next_url}>; rel="next"')
        return _Page([])

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    assert identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref=ref, per_page=per_page) == [{"id": 1}]
    assert calls == [first, next_url]


@pytest.mark.parametrize("repository_id", [123, 456, "123", None, True, 0, -1])
def test_numeric_repository_link_requires_verified_repository_binding(monkeypatch, repository_id):
    """GitHub's documented numeric alias is allowed only for the original repo ID."""
    next_url = _url(2).replace("repos/ContextualWisdomLab/example", "repositories/123")
    metadata_url = "https://api.github.com/repos/ContextualWisdomLab/example"
    calls = []

    def open_page(request, timeout):
        """Bind metadata to the initial owner/name without accepting an arbitrary ID."""
        calls.append(request.full_url)
        if request.full_url == _url():
            return _Page([{"id": 1}], f'<{next_url}>; rel="next"')
        if request.full_url == metadata_url:
            return _Page({"id": repository_id})
        assert repository_id == 123 and type(repository_id) is int, "unverified numeric alias reached transport"
        return _Page([{"id": 2}])

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    if type(repository_id) is int and repository_id == 123:
        assert identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main") == [{"id": 1}, {"id": 2}]
        assert calls == [_url(), metadata_url, next_url]
    else:
        with pytest.raises(identity.ConfigurationIdentityError):
            identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
        assert next_url not in calls


@pytest.mark.parametrize("metadata", [[], {}, {"id": 0}])
def test_numeric_alias_rejects_missing_metadata_identity(monkeypatch, metadata):
    """An unbound metadata payload cannot authorize a numeric analyses endpoint."""
    next_url = _url(2).replace("repos/ContextualWisdomLab/example", "repositories/123")
    calls = []

    def open_page(request, timeout):
        """Serve malformed metadata without ever serving the unverified alias."""
        calls.append(request.full_url)
        if len(calls) == 1:
            return _Page([], f'<{next_url}>; rel="next"')
        assert len(calls) == 2
        return _Page(metadata)

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main")
    assert next_url not in calls


def test_numeric_alias_binding_is_cached_for_later_pages(monkeypatch):
    """One original-repository metadata read binds all numeric page targets."""
    second = _url(2).replace("repos/ContextualWisdomLab/example", "repositories/123")
    third = _url(3).replace("repos/ContextualWisdomLab/example", "repositories/123")
    metadata_url = ENDPOINT.removesuffix("/code-scanning/analyses")
    pages = {_url(): _Page([{"id": 1}], f'<{second}>; rel="next"'),
             metadata_url: _Page({"id": 123}),
             second: _Page([{"id": 2}], f'<{third}>; rel="next"'),
             third: _Page([{"id": 3}])}
    calls = []

    def open_page(request, timeout):
        """Track the single metadata binding and each numeric page."""
        calls.append(request.full_url)
        return pages[request.full_url]

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", open_page)
    assert identity.list_codeql_analyses("ContextualWisdomLab/example", token="opaque", ref="refs/heads/main") == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert calls == list(pages)
