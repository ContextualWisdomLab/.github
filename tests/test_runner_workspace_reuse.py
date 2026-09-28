"""Execute anonymous coverage materialization against a retained runner workspace."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.test_opencode_workflow_shell_syntax import _extract_run_block

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('linked_workspace', [False, True])
def test_anonymous_checkout_cleans_only_its_current_workspace(tmp_path, linked_workspace):
    """Discard old Git hooks/files while preserving sibling and symlink targets."""
    source = tmp_path / 'source'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    (source / 'current.txt').write_text('trusted source\n')
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    parent = tmp_path / 'runner-workspace'
    parent.mkdir()
    workspace = parent / 'repo'
    outside = tmp_path / 'preserved'
    outside.mkdir()
    marker = outside / 'keep.txt'
    marker.write_text('keep\n')
    if linked_workspace:
        workspace.symlink_to(outside, target_is_directory=True)
    else:
        workspace.mkdir()
        subprocess.run(['git', 'init', '-q', str(workspace)], check=True)
        subprocess.run(['git', '-C', str(workspace), 'remote', 'add', 'trusted-source', str(source)], check=True)
        (workspace / 'stale.txt').write_text('old job\n')
        (workspace / 'linked-data').symlink_to(outside, target_is_directory=True)
        hook = workspace / '.git/hooks/post-checkout'
        hook.write_text('#!/bin/sh\ntouch "' + str(outside / 'hook-ran') + '"\n')
        hook.chmod(0o755)
    script = _extract_run_block((ROOT / '.github/workflows/opencode-review-dispatch.yml').read_text(), 'Materialize trusted OpenCode coverage contract without a repository token')
    # Redirect only the fixed public remote to a real local Git fixture.
    script = script.replace('https://github.com/ContextualWisdomLab/.github.git', str(source))
    env = {**os.environ, 'GITHUB_WORKSPACE': str(workspace), 'RUNNER_WORKSPACE': str(parent), 'TRUSTED_SOURCE_REF': sha}
    result = subprocess.run(['bash'], input=script, text=True, cwd=workspace, env=env, capture_output=True)
    assert marker.read_text() == 'keep\n'
    assert not (outside / 'hook-ran').exists()
    if linked_workspace:
        assert result.returncode != 0
        assert not (outside / '.git').exists()
    else:
        assert result.returncode == 0, result.stderr
        assert (workspace / 'current.txt').read_text() == 'trusted source\n'
        assert not (workspace / 'stale.txt').exists()
        assert not (workspace / 'linked-data').exists()
        again = subprocess.run(['bash'], input=script, text=True, cwd=workspace, env=env, capture_output=True)
        assert again.returncode == 0, again.stderr
