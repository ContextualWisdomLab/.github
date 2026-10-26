"""Exercise parsed admission/prepare/publish shells and the full real CLI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'ContextualWisdomLab/traveling-agent'
HEAD = 'bf85ddde01f871f0e713db54aae5a16883777d9f'
ADMIT = 'Admit existing personal LiteLLM auto route'
PREPARE = 'Prepare Noema model verdict'
PUBLISH = 'Publish prepared Noema verdict on the exact live head'
MODE = 'NOEMA_EXACT_CANARY_NON_ZDR'


def _steps():
    """Parse actual YAML instead of supplying a synthetic workflow mapping."""
    document = yaml.load((ROOT / '.github/workflows/noema-review.yml').read_text(), Loader=yaml.BaseLoader)
    return {step['name']: step for step in document['jobs']['noema-review']['steps']}


def _output(path):
    """Read simple runner output records from the actual successful shell."""
    return dict(line.split('=', 1) for line in path.read_text().splitlines()) if path.exists() else {}


def _mode_from_declaration(expression, *, variables, outputs):
    """Evaluate only the workflow's finite mode references, never invent one."""
    match = re.fullmatch(r"\$\{\{ (vars\.[A-Z_]+|steps\.[a-z_]+\.outputs\.[a-z_]+) \|\| 'false' \}\}", expression)
    assert match, 'Unsupported actual canary mode declaration'
    reference = match[1].split('.')
    if reference[0] == 'vars':
        return variables.get(reference[1]) or 'false'
    return outputs.get(reference[1], {}).get(reference[3]) or 'false'


def _run_step(tmp_path, name, phase, case, marker, *, variables, outputs):
    """Run unchanged shell bytes; derive mode exclusively from its declaration."""
    tmp_path.mkdir()
    step = _steps()[name]
    input_path, state_path = tmp_path / 'input.json', tmp_path / 'state.json'
    input_path.write_text(json.dumps({'phase': phase, 'case': case, 'marker': marker}))
    bin_path = tmp_path / 'bin'
    bin_path.mkdir()
    launcher = bin_path / 'python3'
    launcher.write_text('#!/bin/sh\nexec ' + shlex.join([
        sys.executable, '-I', '-B', str(ROOT / 'tests/fixtures/noema_canary_publication_fixture.py')]) + ' "$@"\n')
    launcher.chmod(0o700)
    output = tmp_path / 'outputs'
    # All credentials below are inert external-IO inputs, not real Secrets.
    environment = {'PATH': str(bin_path) + os.pathsep + os.environ['PATH'],
        'HOME': str(tmp_path), 'TMPDIR': str(tmp_path),
        'TARGET_REPOSITORY': REPOSITORY, 'PR_NUMBER': '4', 'EXPECTED_HEAD_SHA': HEAD,
        'GITHUB_WORKSPACE': str(ROOT), 'RUNNER_TEMP': str(tmp_path.parent),
        'GITHUB_OUTPUT': str(output), 'GH_TOKEN': 'synthetic',
        'NOEMA_REVIEW_TOKEN_SOURCE': 'noema-review-github-app-refresh' if phase == 'publish' else 'noema-review-github-app',
        'NOEMA_REVIEW_ACTOR': 'cwl-noema-review[bot]', 'NOEMA_REVIEW_INSTALLATION_ID': '1',
        'NOEMA_EXACT_CANARY_API_KEY': 'synthetic', 'LLM_GATEWAY_API_KEY': 'synthetic',
        'NOEMA_REVIEW_PAID_AUTO_AUTHORIZED': 'false', 'PERSONAL_REVIEW_ZERO_COST_ATTESTED': 'true',
        'PERSONAL_REVIEW_PUBLIC_AUTO_AUTHORIZED': 'false', 'PERSONAL_REVIEW_ZDR_ATTESTED': 'true',
        'PRIVATE_TARGET': 'true', 'PERSONAL_ROUTE_SELECTED': outputs.get('personal_route', {}).get('selected', ''),
        'FIXTURE_SOURCE': str(ROOT), 'FIXTURE_INPUT': str(input_path), 'FIXTURE_STATE': str(state_path)}
    # Step-local Actions env does not persist. Missing Publish env stays absent.
    assert MODE not in environment
    if MODE in step.get('env', {}):
        environment[MODE] = _mode_from_declaration(step['env'][MODE], variables=variables, outputs=outputs)
    command = ['bash', '-c', step['run']]
    if sys.platform == 'darwin':
        profile = ('(version 1)(allow default)(deny network*)(deny file-write*)'
                   '(allow file-write* (subpath ' + json.dumps(str(tmp_path.parent)) + '))')
        command = ['/usr/bin/sandbox-exec', '-p', profile, *command]
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=20)
    (tmp_path / 'stdout.bin').write_bytes(result.stdout)
    (tmp_path / 'stderr.bin').write_bytes(result.stderr)
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    row = {'phase': phase, 'case': case, 'exit': result.returncode,
           'mode_declaration': step.get('env', {}).get(MODE),
           'mode_value': environment.get(MODE), 'outputs': _output(output),
           'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
           'stderr_sha256': hashlib.sha256(result.stderr).hexdigest(),
           'marker_in_logs': marker.encode() in result.stdout + result.stderr,
           'state': state}
    (tmp_path / 'result.json').write_text(json.dumps(row, indent=2))
    return row, result


def _admit_and_prepare(tmp_path, marker, *, mode='true', prepare_case='success'):
    """Connect real policy admission output to real preparation's environment."""
    outputs, variables = {}, {MODE: mode}
    admitted, _ = _run_step(tmp_path / 'admit', ADMIT, 'admit', 'success', marker,
                            variables=variables, outputs=outputs)
    assert admitted['exit'] == 0, 'Actual admission did not succeed'
    outputs['personal_route'] = admitted['outputs']
    assert outputs['personal_route'].get('selected') == 'true'
    assert (outputs['personal_route'].get('exact_canary') == 'true') == (mode == 'true')
    prepared, _ = _run_step(tmp_path / 'prepare', PREPARE, 'prepare', prepare_case, marker,
                            variables=variables, outputs=outputs)
    outputs['noema_prepare'] = prepared['outputs']
    if prepare_case == 'success':
        assert prepared['exit'] == 0 and prepared['outputs'].get('prepared') == 'true'
        envelope = tmp_path / 'noema-verdict-envelope.json'
        assert envelope.is_file() and envelope.stat().st_mode & 0o077 == 0
    return variables, outputs, admitted, prepared


@pytest.mark.parametrize('case', ['pr_nonzero', 'cleanup_os'])
def test_actual_publish_shell_contains_external_failures(tmp_path, case):
    """SEC1: no manual missing-env injection can hide the real composition."""
    marker = 'PRIVATE_PUBLISH_' + uuid.uuid4().hex
    variables, outputs, admitted, prepared = _admit_and_prepare(tmp_path, marker)
    published, result = _run_step(tmp_path / 'publish', PUBLISH, 'publish', case, marker,
                                  variables=variables, outputs=outputs)
    assert result.returncode == 1
    state = published['state']
    assert state['faults'] == ['gh_stderr' if case == 'pr_nonzero' else 'cleanup_os']
    assert state['posts'] == [] and state['requests'] == []
    assert not published['marker_in_logs'], 'Private marker reached actual Publish shell->CLI output'
    assert state['canary_mode'] == 'true'
    assert all('reviewThreads' not in query for query in state['queries'])
    assert not admitted['marker_in_logs'] and not prepared['marker_in_logs']


@pytest.mark.parametrize('mode', ['true', 'false'])
@pytest.mark.parametrize('case,expected_exit,expected_posts', [
    ('success', 0, 1), ('head_drift', 0, 0), ('base_drift', 0, 0),
    ('draft', 0, 0), ('author_drift', 1, 0), ('self_author', 1, 0),
])
def test_connected_publication_preserves_privacy_and_exact_identity(
    tmp_path, mode, case, expected_exit, expected_posts,
):
    """Real admission->prepare->publish preserves normal behavior and guards."""
    marker = 'PRIVATE_PHASE_' + uuid.uuid4().hex
    variables, outputs, admitted, prepared = _admit_and_prepare(tmp_path, marker, mode=mode)
    published, _ = _run_step(tmp_path / 'publish', PUBLISH, 'publish', case, marker,
                             variables=variables, outputs=outputs)
    assert published['exit'] == expected_exit
    state = published['state']
    assert state['canary_mode'] == mode
    assert len(state['posts']) == expected_posts
    assert state['requests'] == []
    assert not (tmp_path / 'noema-verdict-envelope.json').exists()
    assert all(('reviewThreads' not in query) == (mode == 'true') for query in state['queries'])
    assert not any(marker in json.dumps(post) for post in state['posts'])
    if state['posts']:
        assert state['posts'][0]['commit_id'] == HEAD
        assert state['posts'][0]['event'] == 'APPROVE'
        assert 'noema-review-github-app-refresh' in state['posts'][0]['body']
    if mode == 'true':
        assert not any(row['marker_in_logs'] for row in (admitted, prepared, published))
        requests = prepared['state']['requests']
        assert len(requests) == 1 and marker not in requests[0]['data']
        payload = json.loads(requests[0]['data'])
        assert set(payload) == {'model', 'messages', 'response_format'}
        from scripts.ci import noema_exact_canary as policy
        assert payload['model'] == 'auto'
        assert payload['messages'] == [
            {'role': 'system', 'content': policy.SYSTEM},
            {'role': 'user', 'content': policy.INSTRUCTION + 'name: synthetic\non: workflow_dispatch\n'}]
    else:
        # Normal mode intentionally retains its broader context and telemetry.
        assert prepared['marker_in_logs']
        assert marker in prepared['state']['requests'][0]['data']


@pytest.mark.parametrize('case', ['prepare_fsync_os', 'prepare_http'])
def test_connected_preparation_cleanup_and_telemetry_stay_private(tmp_path, case):
    """Real prep failure sinks remain contained with admission-derived mode."""
    marker = 'PRIVATE_PREP_' + uuid.uuid4().hex
    _, outputs, admitted, prepared = _admit_and_prepare(tmp_path, marker, prepare_case=case)
    assert prepared['exit'] == 1
    assert not admitted['marker_in_logs'] and not prepared['marker_in_logs']
    assert not (tmp_path / 'noema-verdict-envelope.json').exists()
    assert outputs['noema_prepare'].get('prepared') != 'true'
    state = prepared['state']
    assert state['canary_mode'] == 'true' and state['posts'] == []
    assert len(state['requests']) == 1
    assert marker not in state['requests'][0]['data']
    assert marker not in json.dumps(outputs)
    if case == 'prepare_fsync_os':
        assert state['faults'] == ['prepare_fsync_os']
    else:
        assert outputs['noema_prepare']['transport_http_status'] == '503'
        assert outputs['noema_prepare']['provider_attempt_count'] == '1'


@pytest.mark.parametrize('case', ['pr_nonzero', 'cleanup_os'])
def test_user_variable_alone_cannot_select_publication_privacy(tmp_path, case):
    """Without the executable admission output, even vars=true stays off."""
    marker = 'NORMAL_PUBLISH_' + uuid.uuid4().hex
    _, outputs, _, _ = _admit_and_prepare(tmp_path, marker, mode='false')
    published, _ = _run_step(tmp_path / 'publish', PUBLISH, 'publish', case, marker,
                             variables={MODE: 'true'}, outputs=outputs)
    assert published['exit'] == 1
    assert published['state']['canary_mode'] == 'false'
    assert published['marker_in_logs']  # unchanged normal-mode diagnostic control
    assert published['state']['posts'] == []


@pytest.mark.parametrize('mode', ['false', 'true'])
def test_admitted_publication_mode_does_not_follow_later_user_variable(tmp_path, mode):
    """The successful admission output, not a later variable, selects mode."""
    marker = 'ADMISSION_BINDING_' + uuid.uuid4().hex
    _, outputs, _, _ = _admit_and_prepare(tmp_path, marker, mode=mode)
    published, _ = _run_step(tmp_path / 'publish', PUBLISH, 'publish', 'success', marker,
                             variables={MODE: 'false' if mode == 'true' else 'true'}, outputs=outputs)
    assert published['exit'] == 0
    assert published['state']['canary_mode'] == mode
    assert len(published['state']['posts']) == 1


@pytest.mark.parametrize('mode', ['', 'invalid'])
def test_invalid_admission_cannot_emit_canary_identity(tmp_path, mode):
    """The trusted shell emits no identity when its executable condition fails."""
    marker = 'DENIED_ADMISSION_' + uuid.uuid4().hex
    admitted, _ = _run_step(tmp_path / 'admit', ADMIT, 'admit', 'success', marker,
                            variables={MODE: mode}, outputs={})
    if mode == '':
        assert admitted['exit'] == 0
        assert 'exact_canary' not in admitted['outputs']
    else:
        assert admitted['exit'] != 0 and admitted['outputs'] == {}
    assert not admitted['marker_in_logs']
