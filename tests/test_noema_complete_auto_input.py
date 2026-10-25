"""Complete source admission through the real Noema serializer (no network)."""
import json
from unittest.mock import patch
import pytest
from scripts.ci import noema_review_gate as gate


def test_real_serializer_preserves_all_locations(monkeypatch):
    monkeypatch.setenv('NOEMA_LLM_MODEL', 'auto')
    monkeypatch.setenv('NOEMA_LLM_API_URL', 'https://litellm.poinnetworks.net/v1/chat/completions')
    monkeypatch.setenv('NOEMA_LLM_API_KEY', 'inert-test-value')
    monkeypatch.setattr(gate, 'reject_private_llm_url', lambda _: None)
    diff = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,1000 @@\n' + '+line\n'*1000
    class Captured(BaseException):
        pass
    requests = []
    def capture(request):
        requests.append(request.data)
        raise Captured()
    with patch.object(gate.urllib.request, 'build_opener') as opener:
        opener.return_value.open.side_effect = capture
        with pytest.raises(Captured):
            gate.call_llm('o/r', 1, {}, diff, False, 'a'*40)
    payload = json.loads(requests[0])
    prompt = payload['messages'][1]['content']
    locations = json.loads(next(line.split(': ', 1)[1] for line in prompt.splitlines()
                                if line.startswith('Allowed changed-side locations: ')))
    assert not locations['truncated']
    assert len(locations['locations']) == 1000
    assert prompt.endswith(diff)
    assert len(requests[0]) <= gate.MAX_AUTO_REVIEW_REQUEST_BYTES


def test_auto_fetch_preserves_complete_diff(monkeypatch):
    monkeypatch.setenv('NOEMA_LLM_MODEL', 'auto')
    monkeypatch.setenv('NOEMA_LLM_API_URL', 'https://litellm.poinnetworks.net/v1/chat/completions')
    diff = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,2 @@\n+' + 'a'*61000 + '\n+final_source_line\n'
    monkeypatch.setattr(gate, 'run', lambda _: diff)
    assert gate.fetch_diff('o/r', 1) == (diff, False)


def test_real_serializer_rejects_oversized_auto_before_network(monkeypatch):
    monkeypatch.setenv('NOEMA_LLM_MODEL', 'auto')
    monkeypatch.setenv('NOEMA_LLM_API_URL', 'https://litellm.poinnetworks.net/v1/chat/completions')
    monkeypatch.setenv('NOEMA_LLM_API_KEY', 'inert-test-value')
    monkeypatch.setattr(gate, 'reject_private_llm_url', lambda _: None)
    with patch.object(gate.urllib.request, 'build_opener') as opener:
        with pytest.raises(RuntimeError, match='complete review input exceeds'):
            gate.call_llm('o/r', 1, {'headRefOid':'a'*40}, '+'+'x'*500000, False, 'a'*40)
        opener.assert_not_called()


@pytest.mark.parametrize('model,url', [('auto','https://example.com/v1/chat/completions'), ('orchestrator/auto','https://litellm.poinnetworks.net/v1/chat/completions')])
def test_other_routes_keep_existing_bound(monkeypatch, model, url):
    monkeypatch.setenv('NOEMA_LLM_MODEL', model)
    monkeypatch.setenv('NOEMA_LLM_API_URL', url)
    monkeypatch.setattr(gate, 'run', lambda _: 'x'*61000)
    text, truncated = gate.fetch_diff('o/r', 1)
    assert truncated and len(text) <= gate.MAX_DIFF_CHARS


def test_auto_rejects_partial_input(monkeypatch):
    monkeypatch.setenv('NOEMA_LLM_MODEL', 'auto')
    monkeypatch.setenv('NOEMA_LLM_API_URL', 'https://litellm.poinnetworks.net/v1/chat/completions')
    monkeypatch.setenv('NOEMA_LLM_API_KEY', 'inert-test-value')
    monkeypatch.setattr(gate, 'reject_private_llm_url', lambda _: None)
    with patch.object(gate.urllib.request, 'build_opener') as opener:
        with pytest.raises(RuntimeError, match='untruncated'):
            gate.call_llm('o/r', 1, {}, 'partial', True, 'a'*40)
        opener.assert_not_called()
