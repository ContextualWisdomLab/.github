"""Contract for the fixed-caller Noema reviewer quality supplier."""
from pathlib import Path

import yaml

PATH = Path('.github/workflows/noema-reviewer-quality.yml')


def workflow():
    """Read the supplier as data; no workflow command is executed here."""
    return yaml.safe_load(PATH.read_text())


def test_supplier_is_fixed_call_only_and_isolated():
    """Reject hosted/privileged fallbacks and caller-selected execution knobs."""
    data = workflow()
    assert data.get('on', data.get(True)) == {'workflow_call': {}}
    assert data['permissions'] == {'contents': 'read'}
    job = data['jobs']['reviewer']
    assert job['runs-on'] == {'group': 'CWL CI isolated', 'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated']}
    assert "github.repository == 'ContextualWisdomLab/noema'" in job['if']
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job['if']
    assert "github.event_name == 'pull_request'" in job['if']
    assert "github.ref == 'refs/heads/main'" in job['if']
    assert 'secrets.' not in PATH.read_text()


def test_original_quality_gates_remain():
    """Keep Python, 100 percent gates, package-install and actual sandbox smoke."""
    job = workflow()['jobs']['reviewer']
    assert job['timeout-minutes'] == 30
    steps = {s['name']: s for s in job['steps']}
    assert steps['setup python']['with']['python-version'] == '3.11'
    assert steps['checkout']['with']['persist-credentials'] is False
    assert 'github.event.pull_request.head.sha' in steps['checkout']['with']['ref']
    assert steps['test noema-core (100% line+branch coverage gate)']['run'] == 'python -m pytest'
    assert steps['test (100% line+branch coverage gate)']['run'] == 'python -m pytest'
    assert 'interrogate' in steps['docstring coverage (100% gate)']['run']
    assert '--require-hashes --no-deps' in steps['install (hash-pinned dependencies)']['run']
    for name in ['smoke-test installed reviewer wheel and sdist-to-wheel path',
                 'smoke-test isolated editable reviewer with locked runtime dependencies',
                 'prepare authenticated and scanned CodeGraph sandbox image',
                 'smoke-test the real no-network CodeGraph sandbox']:
        assert steps[name]['run']
        assert 'continue-on-error' not in steps[name]
    assert 'DockerCodeGraphRunner' in steps['smoke-test the real no-network CodeGraph sandbox']['run']


def test_isolated_tool_and_temporary_state_contract():
    """Require explicit Node/tool availability and job-scoped temporary paths."""
    steps = workflow()['jobs']['reviewer']['steps']
    names = [s['name'] for s in steps]
    assert names.index('Validate fixed caller and required guest capabilities') < names.index('checkout')
    assert names.index('setup node') < names.index('install lock-pinned CodeGraph tooling for sandbox smoke test')
    node = next(s for s in steps if s['name'] == 'setup node')
    assert node['with']['node-version'] == '24.19.0'
    assert 'cache' not in node['with']
    assert 'if' not in node
    assert steps[-1]['if'] == "${{ always() && steps.guest_preflight.outputs.created == 'true' }}"
    assert steps[-1]['working-directory'] == '${{ runner.temp }}'
    for step in steps:
        if 'uses' in step:
            assert len(step['uses'].split('@')[1]) == 40


ORIGINAL_RUN_SHA256 = {'verify exact checkout': 'be4904078076d80c17548dd2dfe04ac8cf920754bb55aed58573c3a688b9c3d4', 'test noema-core (100% line+branch coverage gate)': '88cc0cc55eff4bf0ccdbc9b3d04ecefe2f8d4e10f4aafca9dfd5f467e78e53df', 'docstring coverage noema-core (100% gate)': '0b27ac45cf8a26c48e0491991e03fc314caef56ebe6e8f887b5909b73a63f27b', 'test (100% line+branch coverage gate)': '88cc0cc55eff4bf0ccdbc9b3d04ecefe2f8d4e10f4aafca9dfd5f467e78e53df', 'docstring coverage (100% gate)': 'd0a929f4820c4a1e4b5ab5e11ccdcb02bffd36941cda419887557e3096f62c1a', 'smoke-test installed reviewer wheel and sdist-to-wheel path': 'f620ec6efd06519941b58946a066c2ec826ea676515d76c4a83f9216b18f3936', 'smoke-test isolated editable reviewer with locked runtime dependencies': '6491c954049d08784fe3685760a67b00f3a371d3e57a5e53d0cc423143008273', 'install lock-pinned CodeGraph tooling for sandbox smoke test': '4951c132eec7f7723ce9420b0c7e866bbbb00433cdaa4abffe83e6036eefab72', 'prepare authenticated and scanned CodeGraph sandbox image': '63258b0d6b245ed2a2eeb9557c1202a2d015e656cfe218409c5fd91f4816e9dc', 'smoke-test the real no-network CodeGraph sandbox': '0374b422afe3462054024d793908c2d138547cb6fa3db9d6421a574d7fa1ef4a'}


def test_original_run_bodies_are_preserved():
    """Bind original execution bodies, allowing only job-private temp relocation."""
    import hashlib

    steps = {step["name"]: step for step in workflow()["jobs"]["reviewer"]["steps"]}
    for name, digest in ORIGINAL_RUN_SHA256.items():
        assert hashlib.sha256(steps[name]["run"].encode()).hexdigest() == digest


def test_foreign_or_unsupported_caller_stops_before_tools(tmp_path):
    """Execute the actual preflight and deny callers before any tool invocation."""
    import os
    import subprocess

    script = workflow()['jobs']['reviewer']['steps'][0]['run']
    tool_dir = tmp_path / 'bin'
    tool_dir.mkdir()
    marker = tmp_path / 'tool-invoked'
    for name in ['uname', 'git', 'docker', 'mkdir']:
        tool = tool_dir / name
        tool.write_text(f'#!/bin/sh\n/usr/bin/touch "{marker}"\nexit 97\n')
        tool.chmod(0o700)
    baseline = dict(os.environ, PATH=str(tool_dir),
                    CALLER_REPOSITORY='ContextualWisdomLab/noema',
                    CALLER_EVENT='pull_request', CALLER_REF='refs/pull/1/merge',
                    PR_HEAD_REPOSITORY='ContextualWisdomLab/noema',
                    PR_BASE_REPOSITORY='ContextualWisdomLab/noema')
    for change in [dict(CALLER_REPOSITORY='other/repo'),
                   dict(PR_HEAD_REPOSITORY='fork/noema'),
                   dict(PR_BASE_REPOSITORY='other/repo'),
                   dict(CALLER_EVENT='workflow_dispatch'),
                   dict(CALLER_EVENT='pull_request_target'),
                   dict(CALLER_EVENT='push', CALLER_REF='refs/heads/topic')]:
        result = subprocess.run(['/bin/bash', '-c', script],
                                env=dict(baseline, **change), capture_output=True)
        assert result.returncode != 0
        assert not marker.exists()


def test_cleanup_refuses_unrelated_directory(tmp_path):
    """Run the actual cleaner and preserve paths outside its exact job identity."""
    import os
    import subprocess

    script = workflow()['jobs']['reviewer']['steps'][-1]['run']
    owned = tmp_path / 'noema-reviewer-123-2-reviewer'
    foreign = tmp_path / 'another-job'
    owned.mkdir()
    foreign.mkdir()
    for directory in [owned, foreign]:
        (directory / 'sentinel').write_text('retain unless owned')
    env = dict(os.environ, RUNNER_TEMP=str(tmp_path), GITHUB_RUN_ID='123',
               GITHUB_RUN_ATTEMPT='2', NOEMA_JOB_TEMP=str(foreign))
    denied = subprocess.run(['/bin/bash', '-c', script], env=env, capture_output=True)
    assert denied.returncode != 0 and foreign.exists() and owned.exists()
    accepted = subprocess.run(['/bin/bash', '-c', script],
                              env=dict(env, NOEMA_JOB_TEMP=str(owned)), capture_output=True)
    assert accepted.returncode == 0 and not owned.exists() and foreign.exists()
