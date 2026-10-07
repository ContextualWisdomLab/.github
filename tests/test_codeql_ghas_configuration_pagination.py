"""Synthetic paginated HTTP inputs, not captured GitHub analyses."""
from urllib.parse import parse_qs, urlsplit
import pytest
from scripts.ci import codeql_ghas_configuration_identity as identity

BASE = 'a' * 40
HEAD = 'b' * 40

def row(sha, category='/language:actions'):
    return {'commit_sha': sha, 'category': category, 'analysis_key': identity.DEFAULT_SETUP_ANALYSIS_KEY, 'tool': {'name': 'CodeQL'}}

def test_base_identity_beyond_first_page_must_prevent_false_pairing_pass(monkeypatch):
    calls = []
    def request(url, *, token, timeout_seconds):
        params = parse_qs(urlsplit(url).query)
        page = int(params.get('page', ['1'])[0])
        calls.append(page)
        assert params['ref'] == ['refs/heads/main']
        if page == 1:
            return [row('c' * 40, '/language:python') for _ in range(100)]
        assert page == 2
        return [row(BASE)]
    monkeypatch.setattr(identity, '_request_json', request)
    base = identity.list_codeql_analyses('ContextualWisdomLab/example', token='synthetic-fixture', ref='refs/heads/main')
    ready, missing = identity.pairing_ready(base, [], base_sha=BASE, head_sha=HEAD, language='actions')
    assert ready is False, 'truncated base inventory must not authorize pairing'
    assert missing == [identity.default_setup_identity('actions')]
    assert calls == [1, 2]


def test_head_identity_on_later_page_satisfies_exact_pairing(monkeypatch):
    calls = []
    def request(url, *, token, timeout_seconds):
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        calls.append(page)
        return [row('c' * 40) for _ in range(100)] if page == 1 else [row(HEAD)]
    monkeypatch.setattr(identity, '_request_json', request)
    head = identity.list_codeql_analyses('ContextualWisdomLab/example', token='synthetic-fixture', ref='refs/pull/1/head')
    assert identity.pairing_ready([row(BASE)], head, base_sha=BASE, head_sha=HEAD, language='actions') == (True, [])
    assert calls == [1, 2]


@pytest.mark.parametrize('later', [{'malformed': True}, 'transport_error'])
def test_later_page_error_cannot_return_partial_analyses(monkeypatch, later):
    def request(url, *, token, timeout_seconds):
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        if page == 1:
            return [row(BASE) for _ in range(100)]
        if later == 'transport_error':
            raise identity.ConfigurationIdentityError('synthetic later-page failure')
        return later
    monkeypatch.setattr(identity, '_request_json', request)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses('ContextualWisdomLab/example', token='synthetic-fixture')


@pytest.mark.parametrize('per_page', [0, -1, 101, True, 1.5, '100'])
def test_invalid_page_size_rejected_before_request(monkeypatch, per_page):
    calls = []
    def request(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('invalid page size reached transport')
    monkeypatch.setattr(identity, '_request_json', request)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses('ContextualWisdomLab/example', token='synthetic-fixture', per_page=per_page)
    assert calls == []


def test_full_page_filtered_rows_still_requires_next_page(monkeypatch):
    calls = []
    def request(url, *, token, timeout_seconds):
        page = int(parse_qs(urlsplit(url).query)['page'][0])
        calls.append(page)
        return [None for _ in range(100)] if page == 1 else [row(BASE)]
    monkeypatch.setattr(identity, '_request_json', request)
    assert identity.list_codeql_analyses('ContextualWisdomLab/example', token='synthetic-fixture') == [row(BASE)]
    assert calls == [1, 2]

@pytest.mark.parametrize("boundary", ["codeql-body", "launcher-close", "launcher-long-header"])
def test_http_exception_custody_and_bounded_classification(monkeypatch, boundary):
    """Real modules must bound HTTP diagnostics and settle error streams offline."""
    import io
    import urllib.error
    from scripts.ci import contextual_orchestrator_review_launcher as launcher
    from types import SimpleNamespace

    class Stream(io.BytesIO):
        def __init__(self):
            super().__init__(b"synthetic diagnostic " * 100)
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    stream = Stream()
    error = urllib.error.HTTPError("https://api.github.com/fixture", 429, "synthetic", {"Retry-After": "12"}, stream)
    try:
        if boundary == "codeql-body":
            def refuse(*args, **kwargs):
                raise error
            monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", refuse)
            with pytest.raises(identity.ConfigurationIdentityError):
                identity._request_json("https://api.github.com/fixture", token="synthetic-only", timeout_seconds=1)
            assert stream.read_sizes == [400], "HTTP diagnostic read must be bounded"
            assert stream.closed, "HTTP error must close before propagation"
        elif boundary == "launcher-close":
            row = {"finish_reason": "stale", "reasoning_without_content": True}
            launcher._record_provider_exception(row, error)
            assert row == {"status": "rejected", "error_type": "HTTPError", "http_status": 429, "retry_after_s": 12}
            assert stream.closed, "provider HTTP error must close after classification"
        else:
            try:
                value = launcher._safe_retry_after_seconds(SimpleNamespace(headers={"Retry-After": "9" * 5000}))
            except ValueError:
                pytest.fail("long decimal header escaped safe classification")
            assert value is None
            assert launcher._safe_retry_after_seconds(error) == 12
    finally:
        error.close()
