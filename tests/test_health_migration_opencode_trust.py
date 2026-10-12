"""Execute actual dispatch admission bodies; no API, credentials or models."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

WORKFLOW = Path('.github/workflows/opencode-review-dispatch.yml')


@pytest.mark.parametrize('stage', ['metadata', 'privileged'])
@pytest.mark.parametrize('target', ['ContextualWisdomLab/.github', 'ContextualWisdomLab/product'])
@pytest.mark.parametrize('case', [
    'exact', 'fork', 'missing_head', 'null_head', 'wrong_type_head',
    'stale_head', 'wrong_base', 'missing_visibility', 'wrong_visibility',
    'closed',
])
def test_actual_head_repository_admission(tmp_path, stage, target, case):
    """Same-target exact tuples pass; foreign/missing/stale metadata stops."""
    jobs = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)['jobs']
    if stage == 'metadata':
        step = next(s for s in jobs['validate-pr-metadata']['steps'] if s.get('id') == 'validate')
    else:
        step = next(s for s in jobs['opencode-review-target']['steps']
                    if s.get('name') == 'Validate pull request head repository trust')
    assert shutil.which('jq'), 'Real jq is required'
    base_sha, head_sha = 'a' * 40, 'b' * 40
    pull = {'state': 'open', 'base': {'repo': {'full_name': target, 'visibility': 'private'},
                                    'ref': 'main', 'sha': base_sha},
            'head': {'repo': {'full_name': target}, 'ref': 'review', 'sha': head_sha}}
    pull = copy.deepcopy(pull)
    if case == 'fork':
        pull['head']['repo']['full_name'] = 'Attacker/product'
    elif case == 'missing_head':
        del pull['head']['repo']['full_name']
    elif case == 'null_head':
        pull['head']['repo'] = None
    elif case == 'wrong_type_head':
        pull['head']['repo']['full_name'] = {'full_name': target}
    elif case == 'stale_head':
        pull['head']['sha'] = 'c' * 40
    elif case == 'wrong_base':
        pull['base']['repo']['full_name'] = 'ContextualWisdomLab/other'
    elif case == 'missing_visibility':
        del pull['base']['repo']['visibility']
    elif case == 'wrong_visibility':
        pull['base']['repo']['visibility'] = 'public'
    elif case == 'closed':
        pull['state'] = 'closed'
    fixture = tmp_path / 'pull.json'
    fixture.write_text(json.dumps(pull))
    output = tmp_path / 'output'
    output.touch()
    gh = tmp_path / 'gh'
    gh.write_text('#!/bin/bash\nset -eu\n[[ "$#" = 2 && "$1" = api && "$2" = "$EXPECTED_ENDPOINT" ]] || exit 93\n/bin/cat "$PULL_FIXTURE"\n')
    gh.chmod(0o755)
    env = dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}',
               PULL_FIXTURE=str(fixture), EXPECTED_ENDPOINT=f'repos/{target}/pulls/42',
               GITHUB_OUTPUT=str(output), EVENT_NAME='repository_dispatch',
               DISPATCH_ACTOR='scheduler[bot]', DISPATCH_SENDER='scheduler[bot]',
               ALLOWED_DISPATCH_ACTOR='scheduler[bot]', ALLOWED_DISPATCH_TARGETS=target,
               TARGET_REPOSITORY=target, GH_REPOSITORY=target, PR_NUMBER='42',
               SUPPLIED_BASE_REF='main', SUPPLIED_BASE_SHA=base_sha,
               SUPPLIED_HEAD_REF='review', SUPPLIED_HEAD_SHA=head_sha,
               EXPECTED_BASE_REF='main', EXPECTED_BASE_SHA=base_sha,
               EXPECTED_HEAD_REF='review', EXPECTED_HEAD_SHA=head_sha,
               EXPECTED_IS_PRIVATE='true')
    result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', step['run']],
                            env=env, capture_output=True, text=True, timeout=10)
    # The initial validator derives visibility; the privileged recheck binds it.
    accepted = case == 'exact' or (stage == 'metadata' and case == 'wrong_visibility')
    assert (result.returncode == 0) == accepted, (
        f'{stage}/{target}/{case}: exit={result.returncode}\n{result.stdout}\n{result.stderr}')
    if stage == 'metadata':
        if accepted:
            assert f'target_repository={target}\n' in output.read_text()
            assert f'head_sha={head_sha}\n' in output.read_text()
        else:
            assert not output.read_text(), 'Rejected metadata must not emit trusted outputs'


def test_trust_precedes_privileged_exchange_and_model():
    """Check actual step ordering without pretending to evaluate expressions."""
    steps = yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)['jobs']['opencode-review-target']['steps']
    trust = next(i for i, s in enumerate(steps)
                 if s.get('name') == 'Validate pull request head repository trust')
    assert all(i > trust for i, s in enumerate(steps)
               if s.get('id') in {'opencode_app_token', 'opencode_review_model_pool'})
    assert any(s.get('id') == 'opencode_app_token' for s in steps)
    assert any(s.get('id') == 'opencode_review_model_pool' for s in steps)
