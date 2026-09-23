"""Execute the shipped artifact-metadata boundary with inert API fixtures."""

import json
import os
import re
from pathlib import Path
import subprocess
import textwrap

import pytest

WORKFLOW = Path('.github/workflows/release-dependency-license-strix-gate.yml')


@pytest.mark.parametrize('case', ['valid', 'wrong-id', 'wrong-run', 'missing-digest',
                                  'wrong-digest', 'expired', 'missing-id', 'bad-input-digest',
                                  'wrong-repository', 'api-failure'])
def test_build_artifact_boundary_runs_before_download(tmp_path, case):
    workflow = WORKFLOW.read_text()
    step_name = 'Verify immutable same-run build artifact metadata'
    step = workflow.split('- name: ' + step_name + '\n', 1)[1].split('\n      - ', 1)[0]
    script = textwrap.dedent(step.split('        run: |\n', 1)[1])
    download = workflow.split('- name: Download the exact distributions', 1)[1].split('\n      - ', 1)[0]
    assert 'artifact-ids: ${{ inputs.build_artifact_id }}' in download
    assert 'digest-mismatch: error' in download
    assert 'name: ${{ inputs.build_artifact_name }}' not in download
    assert workflow.index(step_name) < workflow.index('Download the exact distributions')
    assert '      actions: read' in workflow
    for key in ('build_artifact_id', 'build_artifact_digest'):
        declaration = re.split(r'\n      \S', workflow.split('      ' + key + ':\n', 1)[1], maxsplit=1)[0]
        assert 'required: true' in declaration
    digest = 'sha256:' + 'a' * 64
    metadata = dict(id=123, name='dist-pair', digest=digest, workflow_run=dict(id=456), expired=False)
    if case == 'wrong-id': metadata['id'] = 124
    if case == 'wrong-run': metadata['workflow_run']['id'] = 457
    if case == 'missing-digest': metadata.pop('digest')
    if case == 'wrong-digest': metadata['digest'] = 'sha256:' + 'b' * 64
    if case == 'expired': metadata['expired'] = True
    fake = tmp_path / 'gh'
    fake.write_text('#!/bin/sh\n[ "$1" = api ] || exit 91\n'
                    '[ "$2" = /repos/owner/repo/actions/artifacts/123 ] || exit 92\n'
                    '[ "$API_FAILURE" != yes ] || exit 93\n'
                    'printf "%s" "$API_METADATA"\n')
    fake.chmod(0o755)
    marker = tmp_path / 'download-reached'
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'GH_TOKEN': '', 'SOURCE_REPOSITORY': 'other/repo' if case == 'wrong-repository' else 'owner/repo',
           'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_RUN_ID': '456',
           'ARTIFACT_ID': '' if case == 'missing-id' else '123', 'ARTIFACT_NAME': 'dist-pair',
           'ARTIFACT_DIGEST': '' if case == 'bad-input-digest' else digest,
           'API_METADATA': json.dumps(metadata), 'API_FAILURE': 'yes' if case == 'api-failure' else 'no',
           'MARKER': str(marker)}
    result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c',
                             script + '\nprintf reached > "$MARKER"\n'],
                            env=env, capture_output=True, text=True)
    assert (result.returncode == 0) == (case == 'valid'), result.stderr
    assert marker.exists() == (case == 'valid')
