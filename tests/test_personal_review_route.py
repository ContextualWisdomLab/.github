"""Personal wire auto is distinct from an orchestrator alias; policy fails closed."""
import importlib
import json
from pathlib import Path
import pytest


def module():
    assert importlib.util.find_spec('scripts.ci.personal_review_route') is not None, 'Missing personal wire-auto route'
    return importlib.import_module('scripts.ci.personal_review_route')


def test_config_primary_small_reset_preserves_permissions_and_wire_auto(tmp_path):
    route = module()
    path = tmp_path / 'opencode.jsonc'
    path.write_text(json.dumps({'model': 'unsafe/a', 'small_model': 'unsafe/b',
                               'permission': {'edit': 'deny'}, 'agent': {'ci-review': {'steps': 4}}}))
    route.configure_opencode(path)
    result = json.loads(path.read_text())
    assert result['model'] == result['small_model'] == 'personal-litellm/auto'
    assert result['provider']['personal-litellm']['models'].keys() == {'auto'}
    options = result['provider']['personal-litellm']['options']
    assert options == {'baseURL': 'https://litellm.poinnetworks.net/v1',
                       'apiKey': '{env:LLM_GATEWAY_API_KEY}'}
    assert result['permission'] == {'edit': 'deny'}
    assert result['agent']['ci-review']['steps'] == 4


@pytest.mark.parametrize('cost,zdr,private', [(False, True, False), (True, False, True), (False, False, True)])
def test_private_target_without_retention_attestation_stops_before_configuration(cost,zdr,private):
    with pytest.raises(RuntimeError, match='STOP'):
        module().require_admission(zero_cost=cost, zero_retention=zdr, private_target=private)


def test_public_and_private_attested_admission_are_distinct():
    module().require_admission(zero_cost=True, zero_retention=False, private_target=False)
    module().require_admission(zero_cost=True, zero_retention=True, private_target=True)


def test_actual_review_workflows_consume_named_existing_secret_and_auto_route():
    root = Path(__file__).resolve().parents[1]
    noema = (root / '.github/workflows/noema-review.yml').read_text()
    dispatch = (root / '.github/workflows/opencode-review-dispatch.yml').read_text()
    for text in (noema, dispatch):
        assert 'LLM_GATEWAY_API_KEY: ${{ secrets.LLM_GATEWAY_API_KEY }}' in text
        assert 'scripts.ci.personal_review_route' in text
        assert 'PERSONAL_REVIEW_ZERO_COST_ATTESTED' in text
        assert 'PERSONAL_REVIEW_ZDR_ATTESTED' in text
    assert 'export NOEMA_LLM_MODEL="auto"' in noema
    assert 'https://litellm.poinnetworks.net/v1/chat/completions' in noema
    assert '--opencode-config "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc"' in dispatch
    assert 'OPENCODE_MODEL_CANDIDATES="personal-litellm/auto"' in dispatch
    assert 'MODEL="personal-litellm/auto"' in dispatch


@pytest.mark.parametrize('configure', [False, True])
def test_cli_consumes_explicit_policy_and_preserves_config(tmp_path, configure):
    path = tmp_path / 'config.jsonc'
    path.write_text('// trusted comment\n{"permission":{"edit":"deny"}}')
    args = ['--zero-cost', 'true', '--zero-retention', 'true', '--private-target', 'true']
    if configure:
        args += ['--opencode-config', str(path)]
    assert module().main(args) == 0
    if configure:
        assert json.loads(path.read_text())['model'] == 'personal-litellm/auto'
    else:
        assert path.read_text().startswith('// trusted comment')


def test_cli_stop_does_not_write_config_or_assume_attestation(tmp_path):
    path = tmp_path / 'config.jsonc'
    original = '{"permission":{"edit":"deny"}}'
    path.write_text(original)
    with pytest.raises(RuntimeError, match='zero-cost supplier'):
        module().main(['--zero-cost', 'false', '--zero-retention', 'false',
                       '--private-target', 'false', '--opencode-config', str(path)])
    assert path.read_text() == original


def test_module_cli_entry_point_stops_without_policy_inputs(monkeypatch):
    import runpy
    import sys
    monkeypatch.setattr(sys, 'argv', [str(Path(module().__file__))])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(module().__file__)), run_name='__main__')
    assert result.value.code == 2


def test_actual_noema_payload_uses_literal_auto_without_sampling_override(monkeypatch):
    from scripts.ci import noema_review_gate as gate
    from tests.test_noema_review_gate import FakeResponse
    captured = []
    monkeypatch.setenv('NOEMA_LLM_API_URL', 'https://litellm.poinnetworks.net/v1/chat/completions')
    monkeypatch.setenv('NOEMA_LLM_MODEL', 'auto')
    monkeypatch.setenv('NOEMA_LLM_API_KEY', 'synthetic-test-only')
    monkeypatch.setattr(gate, 'validate_substantive_verdict', lambda *_: None)
    monkeypatch.setattr(gate.socket, 'getaddrinfo', lambda *_: [])
    class Opener:
        def open(self, request):
            captured.append((request.full_url, json.loads(request.data)))
            return FakeResponse({'model': 'auto', 'choices': [{'message': {'content': json.dumps({
                'decision': 'comment', 'summary': 'Controlled source-only payload probe.', 'findings': []})}}]})
    monkeypatch.setattr(gate.urllib.request, 'build_opener', lambda *_: Opener())
    verdict = gate.call_llm('ContextualWisdomLab/.github', 2565, {'headRefOid': 'a'*40},
                            '', False, 'a'*40)
    assert verdict['decision'] == 'comment'
    url, body = captured[0]
    assert url == 'https://litellm.poinnetworks.net/v1/chat/completions'
    assert body['model'] == 'auto' and 'temperature' not in body
    assert body['response_format']['type'] == 'json_schema'


def test_authorized_public_route_does_not_assert_supplier_cost():
    module().require_admission(zero_cost=False, zero_retention=False,
                               private_target=False, public_auto_authorized=True)
    for private in (True, None):
        with pytest.raises(RuntimeError, match='zero-cost supplier'):
            module().require_admission(zero_cost=False, zero_retention=True,
                                       private_target=private, public_auto_authorized=True)
    for authorization in (False, None, 'true', 1):
        with pytest.raises(RuntimeError, match='zero-cost supplier'):
            module().require_admission(zero_cost=False, zero_retention=True,
                                       private_target=False, public_auto_authorized=authorization)


def test_public_authorization_cli_cannot_release_private_configuration(tmp_path):
    path = tmp_path / 'config.json'
    original = '{"permission":{"edit":"deny"}}'
    path.write_text(original)
    base = ['--zero-cost', 'false', '--zero-retention', 'false',
            '--public-auto-authorized', 'true']
    assert module().main(base + ['--private-target', 'false']) == 0
    with pytest.raises(RuntimeError, match='zero-cost supplier'):
        module().main(base + ['--private-target', 'true', '--opencode-config', str(path)])
    assert path.read_text() == original
