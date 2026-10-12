"""Source-only trust gate: real YAML Bash, inert API, no company operation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/company-default-head-trust-gate.yml'
CURRENT = 'a' * 40


def workflow():
    assert WORKFLOW.is_file(), 'Missing central company trust-gate callee'
    return yaml.safe_load(WORKFLOW.read_text())


def test_exact_callee_contract():
    data = workflow()
    trigger = data.get('on', data.get(True))
    assert set(trigger) == {'workflow_call'}
    call = trigger['workflow_call']
    assert set(call['inputs']) == {'target_runner_label', 'trusted_ref_sha', 'trusted_ref_ack'}
    assert call['inputs']['target_runner_label'] == {'required': True, 'type': 'string'}
    assert call.get('secrets', {}) == {}
    assert call['outputs']['runner_matrix']['value'] == '${{ jobs.validate.outputs.runner_matrix }}'
    assert data['permissions'] == {'contents': 'read'}
    assert set(data['jobs']) == {'validate'}
    job = data['jobs']['validate']
    assert job['runs-on'] == {'group': 'CWL CI isolated',
                             'labels': ['self-hosted', 'Linux', 'X64', 'cwlab-ci-isolated']}
    assert job['timeout-minutes'] == 5
    assert job['outputs']['runner_matrix'] == '${{ steps.runner.outputs.runner_matrix }}'
    assert len(job['steps']) == 2
    assert all('uses' not in step and step['shell'] == 'bash' for step in job['steps'])
    body = '\n'.join(step['run'] for step in job['steps'])
    assert 'inputs.trusted_ref_' not in body
    assert 'secrets.' not in body
    assert job['steps'][1]['env']['GH_TOKEN'] == '${{ github.token }}'


@pytest.mark.parametrize('case,ref,target,api_exit,sha,expected,calls', [
    ('current', 'main', 'all', 0, CURRENT, 0, 1),
    ('stale', 'main', 'itxllmpgw01', 0, 'b' * 40, 2, 1),
    ('nondefault', 'feature', 'itxllmpgw01', 0, CURRENT, 2, 0),
    ('invalid-target', 'main', 'injected; echo unsafe', 0, CURRENT, 2, 0),
    ('api-failure', 'main', 'itxllmpgw01', 23, CURRENT, 23, 1),
])
def test_actual_callee_bash(tmp_path, case, ref, target, api_exit, sha, expected, calls):
    job = workflow()['jobs']['validate']
    stub = tmp_path / 'gh'
    stub.write_text('#!' + sys.executable + '\n'
                    'import json, os, sys\n'
                    'with open(os.environ["CALLS"], "a") as f:\n'
                    ' f.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                    'if int(os.environ["API_EXIT"]): sys.exit(int(os.environ["API_EXIT"]))\n'
                    'print(os.environ["CURRENT_SHA"])\n')
    stub.chmod(0o700)
    output, record = tmp_path / 'output', tmp_path / 'calls'
    env = {'PATH': str(tmp_path) + os.pathsep + os.defpath,
           'TARGET': target, 'DEFAULT_BRANCH': 'main', 'REF_NAME': ref,
           'SHA': sha, 'REPOSITORY': 'fixture/company-ops', 'GH_TOKEN': 'synthetic-only',
           'GITHUB_OUTPUT': str(output), 'CALLS': str(record),
           'CURRENT_SHA': CURRENT, 'API_EXIT': str(api_exit)}
    bash = shutil.which('bash')
    assert bash, 'Bash is required; missing tool is not a skipped PASS'
    results = []
    for step in job['steps']:
        result = subprocess.run([bash, '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step['run']],
                                env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10)
        results.append(result)
        if result.returncode:
            break
    assert results[-1].returncode == expected, (case, results[-1].stderr)
    actual_calls = record.read_text().splitlines() if record.exists() else []
    assert len(actual_calls) == calls
    for line in actual_calls:
        assert json.loads(line) == ['api', 'repos/fixture/company-ops/commits/main', '--jq', '.sha']
    if case == 'invalid-target':
        assert not output.exists()
    else:
        value = output.read_text().strip().removeprefix('runner_matrix=')
        assert json.loads(value) == (['itxllmpgw01', 'itxllmpgw02', 'xtrmsales-llmgw1',
                                     'xtrmsales-llmgw2'] if target == 'all' else [target])
    if case == 'current':
        assert 'trusted_ref_status=current_default_head' in results[-1].stdout
    else:
        assert 'trusted_ref_status=current_default_head' not in results[-1].stdout


@pytest.mark.parametrize('result', ['success', 'failure', 'cancelled', 'skipped'])
def test_always_downstream_requires_overall_success(result):
    # Source caller fixture/truth table, not GitHub scheduling or operating execution.
    data = workflow()
    fixture = yaml.safe_load('''jobs:
  trust:
    uses: ContextualWisdomLab/.github/.github/workflows/company-default-head-trust-gate.yml@<reviewed-sha>
  operate:
    needs: trust
    if: ${{ always() && needs.trust.result == 'success' }}
    matrix_data: ${{ needs.trust.outputs.runner_matrix }}
''')
    assert data['jobs']['validate']['outputs']['runner_matrix']
    job = fixture['jobs']['operate']
    assert job['needs'] == 'trust'
    assert job['if'] == "${{ always() && needs.trust.result == 'success' }}"
    produced_matrix = '["itxllmpgw01"]'  # Can exist even on stale/nondefault failure.
    assert produced_matrix
    # Exercise the supported fixture predicate with supplied result as data.
    predicate = job['if'].removeprefix('${{ ').removesuffix(' }}')
    assert predicate == "always() && needs.trust.result == 'success'"
    shell = predicate.replace('always()', 'true').replace(
        "needs.trust.result == 'success'", '[ "$TRUST_RESULT" = success ]')
    bash = shutil.which('bash')
    assert bash
    child = subprocess.run([bash, '--noprofile', '--norc', '-c',
                            'if ' + shell + '; then printf admitted; fi'],
                           env={'TRUST_RESULT': result}, capture_output=True,
                           text=True, timeout=5)
    assert child.returncode == 0
    assert child.stdout == ('admitted' if result == 'success' else '')
    # Removing the success gate admits all failed/skipped fixtures: oracle sensitivity.
    unsafe = subprocess.run([bash, '--noprofile', '--norc', '-c',
                             'if true; then printf admitted; fi'],
                            env={'TRUST_RESULT': result}, capture_output=True,
                            text=True, timeout=5)
    assert unsafe.stdout == 'admitted'
