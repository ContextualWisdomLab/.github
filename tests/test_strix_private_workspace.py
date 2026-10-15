"""Behavioral contracts for Strix job-private trusted checkout ownership."""
from pathlib import Path

import yaml

WORKFLOW = Path('.github/workflows/strix.yml')


def steps():
    """Read executable steps of the substantive Strix job."""
    return yaml.safe_load(WORKFLOW.read_text())['jobs']['strix']['steps']


def test_workspace_allocator_precedes_both_materialization_routes():
    """Never initialize a checkout in shared fixed runner temporary state."""
    sequence = steps()
    names = [step['name'] for step in sequence]
    allocation = names.index('Allocate job-private trusted workspace')
    for name in ['Materialize target workspace', 'Validate repository dispatch against live pull request metadata']:
        assert allocation < names.index(name)
        run = sequence[names.index(name)]['run']
        assert 'trusted_workspace="$TRUSTED_WORKSPACE"' in run
        assert 'mkdir -p "$trusted_workspace"' not in run
    scan = sequence[names.index('Run Strix (quick)')]
    assert scan['working-directory'] == '${{ steps.trusted_workspace.outputs.path }}'
    assert scan['env']['STRIX_REPO_ROOT'] == '${{ steps.trusted_workspace.outputs.path }}'


def payload(name):
    """Extract the exact embedded Python body, excluding the shell wrapper."""
    run = next(step['run'] for step in steps() if step['name'] == name)
    return run.split("python3 - <<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]


def allocate(monkeypatch, parent, output, environment):
    """Execute the real allocator against synthetic local runner paths."""
    monkeypatch.setenv('RUNNER_TEMP', str(parent))
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_ENV', str(environment))
    exec(compile(payload('Allocate job-private trusted workspace'), '<allocator>', 'exec'), {})
    return dict(line.split('=', 1) for line in output.read_text().splitlines())


def test_two_allocations_preserve_preexisting_workspace(monkeypatch, tmp_path):
    """Never reuse the residue that caused remote-origin-already-exists failures."""
    parent = tmp_path / 'runner'
    parent.mkdir()
    old = parent / 'trusted-workspace'
    old.mkdir()
    (old / 'sentinel').write_text('other job')
    a = allocate(monkeypatch, parent, tmp_path / 'out1', tmp_path / 'env1')
    b = allocate(monkeypatch, parent, tmp_path / 'out2', tmp_path / 'env2')
    assert a['path'] != b['path']
    assert Path(a['path']).stat().st_mode & 0o777 == 0o700
    assert (old / 'sentinel').read_text() == 'other job'


def test_allocator_handoff_failure_removes_only_new_root(monkeypatch, tmp_path):
    """Failed environment publication leaves no newly allocated directory."""
    import pytest

    parent = tmp_path / 'runner'
    parent.mkdir()
    sentinel = parent / 'keep'
    sentinel.mkdir()
    with pytest.raises(IsADirectoryError):
        allocate(monkeypatch, parent, tmp_path / 'out', tmp_path)
    assert list(parent.iterdir()) == [sentinel]


def test_cleanup_checks_directory_identity(monkeypatch, tmp_path):
    """Replacement directories and links never authorize deletion of another job."""
    import pytest

    parent = tmp_path / 'runner'
    parent.mkdir()
    owned = allocate(monkeypatch, parent, tmp_path / 'out', tmp_path / 'env')
    root = Path(owned['path'])
    monkeypatch.setenv('OWNED_WORKSPACE', str(root))
    monkeypatch.setenv('OWNED_WORKSPACE_DEVICE', owned['device'])
    monkeypatch.setenv('OWNED_WORKSPACE_INODE', str(int(owned['inode']) + 1))
    script = compile(payload("Clean up this job's trusted workspace"), '<cleanup>', 'exec')
    with pytest.raises(RuntimeError, match='identity'):
        exec(script, {})
    assert root.exists()
    monkeypatch.setenv('OWNED_WORKSPACE_INODE', owned['inode'])
    exec(script, {})
    assert not root.exists()
    exec(script, {})  # repeated cleanup is harmless


def test_allocator_refuses_symlink_ancestry(monkeypatch, tmp_path):
    """Do not allocate a trusted checkout through redirected runner ancestry."""
    import pytest

    real = tmp_path / 'real'
    real.mkdir()
    linked = tmp_path / 'linked'
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(RuntimeError, match='ancestry'):
        allocate(monkeypatch, linked, tmp_path / 'out', tmp_path / 'env')
    assert not list(real.iterdir())


def test_materialization_replays_with_old_remote_residue(monkeypatch, tmp_path):
    """Two real Git checkouts succeed while an old fixed-path origin is untouched."""
    import os
    import subprocess

    parent = tmp_path / 'runner'
    parent.mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    git_env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    def git(*args):
        """Run local Git only; no network or real credential helper is involved."""
        return subprocess.check_output(['git', *map(str, args)], env=git_env, stderr=subprocess.DEVNULL, text=True).strip()
    git('init', source)
    (source / 'tracked.txt').write_text('trusted source')
    git('-C', source, 'add', 'tracked.txt')
    git('-C', source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
    sha = git('-C', source, 'rev-parse', 'HEAD')
    bare = tmp_path / 'upstream' / 'ContextualWisdomLab' / 'demo.git'
    bare.parent.mkdir(parents=True)
    git('clone', '--bare', source, bare)
    old = parent / 'trusted-workspace'
    git('init', old)
    git('-C', old, 'remote', 'add', 'origin', 'https://example.invalid/old.git')
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    fake_gh = fake_bin / 'gh'
    fake_gh.write_text('#!/bin/sh\ntest "$*" = "auth setup-git"\n')
    fake_gh.chmod(0o700)
    script = next(step['run'] for step in steps() if step['name'] == 'Materialize target workspace')
    for attempt in range(2):
        environment = tmp_path / f'env{attempt}'
        owned = allocate(monkeypatch, parent, tmp_path / f'out{attempt}', environment)
        env = dict(git_env, PATH=f"{fake_bin}:{os.environ['PATH']}", RUNNER_TEMP=str(parent),
                   TRUSTED_WORKSPACE=owned['path'], GITHUB_ENV=str(environment),
                   GITHUB_SERVER_URL=str(tmp_path / 'upstream'),
                   REPOSITORY='ContextualWisdomLab/demo', TARGET_WORKSPACE_SHA=sha)
        result = subprocess.run(['/bin/bash', '-c', script], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert git('-C', owned['path'], 'rev-parse', 'HEAD') == sha
    assert git('-C', old, 'remote', 'get-url', 'origin') == 'https://example.invalid/old.git'
