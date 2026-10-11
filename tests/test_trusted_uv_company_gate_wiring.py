"""Verify company trust-gate changes reach the existing complete quality gate."""
from fnmatch import fnmatchcase
from pathlib import Path
import shlex

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / '.github/workflows/trusted-uv-materializer-quality-ci.yml'
SURFACES = (
    '.github/workflows/company-default-head-trust-gate.yml',
    'tests/test_company_default_head_trust_gate.py',
)


def quality():
    return yaml.safe_load(QUALITY.read_text())


@pytest.mark.parametrize('event', ['pull_request', 'push'])
@pytest.mark.parametrize('surface', SURFACES)
def test_trust_gate_change_selects_existing_quality(event, surface):
    data = quality()
    triggers = data.get('on', data.get(True))
    patterns = triggers[event]['paths']
    assert any(fnmatchcase(surface, pattern) for pattern in patterns), (
        event, surface, 'Trust-gate change does not select existing full quality gate')
    # Each new exact surface is necessary: prove selector sensitivity offline.
    without = [p for p in patterns if p != surface]
    assert not any(fnmatchcase(surface, p) for p in without)


def test_selected_quality_command_discovers_trust_gate_regression():
    data = quality()
    job = data['jobs']['full-quality-gate']
    step = next(s for s in job['steps']
                if s.get('name') == 'Run complete central test and branch coverage gate')
    commands = [shlex.split(line) for line in step['run'].splitlines() if line.strip()]
    assert ['python', '-m', 'coverage', 'run', '-m', 'pytest', 'tests', '-q'] in commands
    assert ['python', '-m', 'coverage', 'report'] in commands
    assert ['unset', 'COVERAGE_RCFILE'] in commands
    module = ROOT / SURFACES[1]
    assert module.is_file() and module.name.startswith('test_') and module.suffix == '.py'
    assert module.parent == ROOT / 'tests'
    assert data['permissions'] == {'contents': 'read'}
    assert job['name'] == 'Python 3.14 full quality gate'
    assert job['runs-on'] == {'group': 'CWL CI isolated',
                             'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated']}
