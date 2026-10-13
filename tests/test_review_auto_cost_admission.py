"""Exercise complete launcher selection with inert library/provider collaborators."""
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('only_priced', [False, True])
def test_auto_zero_cost_main_never_preflights_or_serves_priced_models(tmp_path, monkeypatch, only_priced):
    namespace = runpy.run_path(str(ROOT / 'scripts/ci/contextual_orchestrator_review_launcher.py'))
    main = namespace['main']
    globalns = main.__globals__
    free = SimpleNamespace(provider_name='openrouter', model_id='qwen/qwen3-coder:free',
                           agent_id='openrouter_free_model', output_modalities=('text',),
                           prompt_price_per_1k=0.0, completion_price_per_1k=0.0,
                           currency_code='USD')
    priced = SimpleNamespace(provider_name='openai', model_id='priced-model',
                             agent_id='openai_priced_model', output_modalities=('text',),
                             prompt_price_per_1k=0.1, completion_price_per_1k=0.2,
                             currency_code='USD')
    observed = {'preflight': [], 'served': []}
    modules = {
        'credentials': {'get_credential': lambda _: 'synthetic-only'},
        'chat_capability': {'is_general_chat_agent_model_id': lambda _: True},
        'model_discovery': {'discover_all_models': lambda: ([priced] if only_priced else [free, priced], {}),
                            'free_discovered_models': lambda rows: [m for m in rows if m is free]},
        'review_gateway': {'REVIEW_AUTH_CREDENTIAL_NAME': 'fixture',
                           'register_review_credentials': lambda _: ['OPENROUTER_API_KEY']},
        'debug_logging': {'configure_logging': lambda **_: None},
    }
    def load_agents(path):
        return json.loads(Path(path).read_text())['agents']
    class ModelClient:
        def __init__(self, **kwargs):
            pass
    class TaskOrchestrator:
        def __init__(self, agents, **kwargs):
            self.agents = agents
    modules['orchestrator'] = {'load_agents': load_agents, 'ModelClient': ModelClient,
                               'TaskOrchestrator': TaskOrchestrator}
    modules['server'] = {'SecurityConfig': lambda **kwargs: kwargs,
                         'serve': lambda orchestrator, **kwargs: observed['served'].extend(orchestrator.agents)}
    package = ModuleType('contextual_orchestrator')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, 'contextual_orchestrator', package)
    for name, values in modules.items():
        module = ModuleType('contextual_orchestrator.' + name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(globalns, '_configure_sidecar_logging', lambda _: None)
    monkeypatch.setitem(globalns, '_log_discovery_errors', lambda _: None)
    def preflight(primary, fallback, **kwargs):
        assert not fallback, 'zero-cost mode may not prepare paid fallback'
        assert all(a['model'] != 'priced-model' for a in primary)
        observed['preflight'].extend(primary)
        return primary, {'ready': True}, False
    monkeypatch.setitem(globalns, '_preflight_with_fallback', preflight)
    argv = ['--pool', 'auto', '--zero-cost-only']
    for flag in ('discovery-out', 'catalog-out', 'report-out', 'preflight-out'):
        argv.extend(['--' + flag, str(tmp_path / (flag + '.json'))])
    if only_priced:
        with pytest.raises(SystemExit, match='no eligible models; orchestrator/auto'):
            main(argv)
        assert not observed['preflight'] and not observed['served']
    else:
        assert main(argv) == 0
        assert [a['model'] for a in observed['served']] == [free.model_id]
        report = json.loads((tmp_path / 'report-out.json').read_text())
        assert report['requested_pool'] == 'orchestrator/auto'
        assert report['zero_cost_only'] is True
        assert report['priced_selected_count'] == report['unknown_selected_count'] == 0


@pytest.mark.parametrize('private_target', [False, True])
def test_fenced_auto_rejects_primary_failure_without_priced_fallback(
    tmp_path, monkeypatch, private_target,
):
    """Execute real launcher preflight/policy with controlled provider calls."""
    from scripts.ci import contextual_orchestrator_review_launcher as launcher
    from tests.test_contextual_orchestrator_review_launcher import (
        _discovered_model, _install_owner_runtime, _launcher_arguments,
    )
    free = _discovered_model()
    priced = _discovered_model(
        provider_name='openai', model_id='gpt-priced', agent_id='openai_priced',
        credential_name='OPENAI_API_KEY', prompt_price=1.0, completion_price=2.0,
    )
    state = _install_owner_runtime(
        monkeypatch, discovered_models=[free, priced],
        registered_credentials=['BYTEZ_API_KEY', 'OPENAI_API_KEY'],
        failing_agent_ids=frozenset({'bytez_free'}),
    )
    extra = ['--pool', 'auto', '--zero-cost-only']
    if private_target:
        extra.append('--require-zdr')
    from scripts.ci.contextual_orchestrator_review_policy import PolicyError
    rejection = PolicyError if private_target else SystemExit
    with pytest.raises(rejection):
        launcher.main(_launcher_arguments(tmp_path, *extra))
    assert not state.served_requests
    catalog = tmp_path / 'catalog.json'
    if catalog.exists():
        agents = json.loads(catalog.read_text())['agents']
        assert all(a['model'] != 'gpt-priced' for a in agents)
    assert not (tmp_path / 'catalog.json.priced').exists()
