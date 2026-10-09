"""Validate the central settlement workload callee source boundary."""
import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/company-settlement-validate.yml'
QUALITY = ROOT / '.github/workflows/trusted-uv-materializer-quality-ci.yml'
EXPECTED_STEPS_HASH = '0d549f21d485446af03f440c374fa701720340c6961bbac1e02c3987d89522b0'
EXPECTED_TEST_MODULES = (
    'tests/test_issue119_pgcat_endpoint_resolver.py',
    'tests/test_issue119_settlement_live_verify.py',
    'tests/test_issue119_settlement_replica_routing.py',
    'tests/test_issue119_settlement_review_regressions.py',
    'tests/test_multi_instance_runtime_contract.py',
)


def load(path: Path):
    assert path.is_file(), f'missing {path.relative_to(ROOT)}'
    return yaml.safe_load(path.read_text())


def test_settlement_callee_has_fixed_isolated_selector_and_no_caller_selected_runner():
    data = load(WORKFLOW)
    trigger = data.get('on', data.get(True))
    assert set(trigger) == {'workflow_call'}
    call = trigger['workflow_call']
    assert call.get('inputs', {}) == {}
    assert call.get('secrets', {}) == {}
    assert data['permissions'] == {'contents': 'read'}
    assert set(data['jobs']) == {'validate'}
    job = data['jobs']['validate']
    assert job['runs-on'] == {
        'group': 'CWL CI isolated',
        'labels': ['self-hosted', 'Linux', 'X64', 'cwlab-ci-isolated'],
    }
    assert 'runner_group' not in WORKFLOW.read_text()
    assert 'runner_labels_json' not in WORKFLOW.read_text()
    assert 'fromJSON' not in WORKFLOW.read_text()


def test_settlement_callee_preserves_reviewed_workload_bytes_and_security_boundary():
    data = load(WORKFLOW)
    job = data['jobs']['validate']
    assert len(job['steps']) == 7
    body = WORKFLOW.read_bytes()
    steps_bytes = body[body.index(b'    steps:\n'):]
    # Supplier's trailing blank line is not workload; preserve every actual step byte.
    assert hashlib.sha256(steps_bytes.rstrip(b'\n') + b'\n\n').hexdigest() == EXPECTED_STEPS_HASH
    assert job['steps'][0]['uses'] == 'actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd'
    assert job['steps'][0]['with'] == {
        'persist-credentials': False,
        'ref': '${{ github.event.pull_request.head.sha || github.sha }}',
    }
    assert job['steps'][1]['uses'] == 'actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97'
    assert job['steps'][1]['with'] == {'python-version': '3.13'}
    assert job['steps'][2]['uses'] == 'astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4'
    verify = job['steps'][5]
    assert verify['env'] == {'SETTLEMENT_VERIFY_REQUIRE_POSTGRES': '1'}
    for module in EXPECTED_TEST_MODULES:
        assert module in verify['run']
    assert 'DATABASE_' not in yaml.safe_dump(job)
    assert 'secrets.' not in yaml.safe_dump(job)


def test_settlement_callee_is_selected_by_existing_complete_quality_gate():
    data = load(QUALITY)
    trigger = data.get('on', data.get(True))
    for event in ('pull_request', 'push'):
        paths = trigger[event]['paths']
        assert '.github/workflows/company-settlement-validate.yml' in paths
        assert 'tests/test_trusted_uv*.py' in paths
        assert Path(__file__).match('test_trusted_uv*.py')
    full = data['jobs']['full-quality-gate']
    step = next(s for s in full['steps'] if s.get('name') == 'Run complete central test and branch coverage gate')
    assert 'python -m coverage run -m pytest tests -q' in step['run']
    assert full['runs-on'] == {
        'group': 'CWL CI isolated',
        'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated'],
    }
    assert data['permissions'] == {'contents': 'read'}
