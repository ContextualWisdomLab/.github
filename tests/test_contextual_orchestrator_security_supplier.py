"""Source-only contracts for the existing central owner's proposed CO supplier.

No Actions dispatch or timing assertion; all commands below inspect private bytes.
"""
from copy import deepcopy
from pathlib import Path
import re
import subprocess
import shutil
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/contextual-orchestrator-security.yml'
BASE = Path(__file__).with_name('fixtures') / 'contextual-orchestrator-security-8c8daebf.yml'

class Loader(yaml.SafeLoader):
    """Use YAML 1.2 Boolean spelling without mutating ordinary SafeLoader."""

Loader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in values if tag != 'tag:yaml.org,2002:bool']
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Loader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false|True|False|TRUE|FALSE)$'), list('tTfF'))

def load(path):
    return yaml.load(path.read_text(), Loader=Loader)

def assert_supplier(current):
    """Reject placement, admission, permission or executable workload drift."""
    base = load(BASE)
    assert current['on'] == {'workflow_call': {}}, 'missing reusable callee'
    assert current['permissions'] == base['permissions']
    assert 'concurrency' not in current, 'caller owns unchanged concurrency'
    assert list(current['jobs']) == ['tests', 'fuzz', 'rust', 'security']
    for name, old in base['jobs'].items():
        job = current['jobs'][name]
        assert job['runs-on'] == {'group':'CWL CI isolated', 'labels':['self-hosted','linux','x64','cwlab-ci-isolated']}
        assert job['if'] == "github.repository == 'ContextualWisdomLab/contextual-orchestrator' && (" + old['if'] + ')'
        for key in ('name','permissions','defaults'):
            assert job.get(key) == old.get(key)
        expected_steps = deepcopy(old['steps'])
        if name == 'security':
            upload = next(s for s in expected_steps if s['name'] == 'Upload CodeQL SARIF with transient retries')
            upload['run'] = upload['run'].replace(
                '    exit 0\n  fi\n  status=$?\n',
                '    exit 0\n  else\n    status=$?\n  fi\n')
        assert job['steps'] == expected_steps
    assert 'secrets' not in current['on']['workflow_call']
    assert not any('secrets' in j for j in current['jobs'].values())


def test_fixed_caller_supplier_keeps_every_security_workload():
    """Centralization preserves the complete executable four-job source."""
    assert_supplier(load(WORKFLOW))


@pytest.mark.parametrize('mutation', ['label', 'privileged', 'hosted', 'workload',
                                    'secrets', 'caller', 'permission', 'tolerant'])
def test_supplier_contract_rejects_otherwise_valid_drift(mutation):
    """Sensitivity controls for the shared actual-source oracle, not CI admission."""
    current = deepcopy(load(WORKFLOW))
    job = current['jobs']['tests']
    if mutation == 'label':
        job['runs-on']['labels'].remove('cwlab-ci-isolated')
    elif mutation == 'privileged':
        job['runs-on']['group'] = 'CWL central control'
    elif mutation == 'hosted':
        job['runs-on'] = 'ubuntu-24.04'
    elif mutation == 'workload':
        next(s for s in job['steps'] if s['name'] == 'Run full test suite')['run'] = 'echo omitted'
    elif mutation == 'secrets':
        current['on']['workflow_call']['secrets'] = {'KEY':{'required':True}}
    elif mutation == 'caller':
        job['if'] = load(BASE)['jobs']['tests']['if']
    elif mutation == 'permission':
        job['permissions'] = {'contents':'write'}
    elif mutation == 'tolerant':
        job['steps'][0]['continue-on-error'] = True
    with pytest.raises(AssertionError):
        assert_supplier(current)


@pytest.mark.parametrize('statuses,expected_calls,expected_exit', [
    ('19', 5, 19), ('0', 1, 0), ('19,19,0', 3, 0)])
def test_sarif_upload_terminal_status(tmp_path, statuses, expected_calls, expected_exit):
    """Execute the actual uploader with synthetic command adapters, no network."""
    workflow = load(WORKFLOW)
    step = next(s for s in workflow['jobs']['security']['steps']
                if s['name'] == 'Upload CodeQL SARIF with transient retries')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    log = tmp_path / 'calls'
    status_values = statuses.split(',')
    cases = '\n'.join(f'{i}) exit {status} ;;' for i, status in enumerate(status_values, 1))
    codeql = 'printf "attempt\\n" >> "$CALL_LOG"\ncase $(wc -l < "$CALL_LOG" | tr -d " ") in\n' + cases + '\n*) exit 19 ;;\nesac'
    for name, body in [('codeql', codeql), ('sleep', 'exit 0')]:
        path = bin_dir / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)
    sarif_dir = tmp_path / 'sarif'
    sarif_dir.mkdir()
    (sarif_dir / 'python.sarif').write_text('{"runs":[]}')
    bash = shutil.which('bash')
    assert bash, 'Bash is mandatory for workflow source contracts'
    result = subprocess.run([bash, '-c', step['run']],
        cwd=tmp_path, text=True, capture_output=True, timeout=30,
        env={'PATH': str(bin_dir) + ':/usr/bin:/bin', 'SARIF_DIR':str(sarif_dir),
             'CALL_LOG':str(log), 'GITHUB_TOKEN':'synthetic-fixture-token',
             'EVENT_NAME':'push','PR_NUMBER':'','GITHUB_REF_NAME':'refs/heads/main',
             'GITHUB_SHA_VALUE':'a'*40,
             'GITHUB_REPOSITORY_VALUE':'ContextualWisdomLab/contextual-orchestrator'})
    assert log.read_text().splitlines() == ['attempt'] * expected_calls
    assert result.returncode == expected_exit, result.stdout + result.stderr
