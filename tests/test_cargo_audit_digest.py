"""Offline execution of the actual installer; only download bytes are synthetic."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

from tests.test_contextual_orchestrator_security_supplier import load, WORKFLOW

DIGEST = 'ab28a1bdb54db4d5d8ad5981cf1f959410370b3d28250dbd35f6a44248620e39'


def installer():
    return next(s['run'] for s in load(WORKFLOW)['jobs']['rust']['steps']
                if s['name'] == 'Install cargo-audit')


def run_installer(tmp_path, script, valid=False):
    """Use real SHA256/tar/install and an inert fixture executable, never releases."""
    archive = tmp_path / 'fixture.tgz'
    body = b'#!/bin/sh\nprintf "exec\\n" >> "$CALL_LOG"\n'
    with tarfile.open(archive, 'w:gz') as tar:
        member = tarfile.TarInfo('cargo-audit-x86_64-unknown-linux-gnu-v0.22.2/cargo-audit')
        member.mode = 0o755
        member.size = len(body)
        tar.addfile(member, io.BytesIO(body))
    if valid:
        script = script.replace(DIGEST, hashlib.sha256(archive.read_bytes()).hexdigest())
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in ('tar', 'install'):
        native = shutil.which(name)
        assert native
        wrapper = bin_dir / name
        wrapper.write_text(f'#!/bin/sh\nprintf "{name}\\n" >> "$CALL_LOG"\nexec "{native}" "$@"\n')
        wrapper.chmod(0o755)
    sha = shutil.which('sha256sum')
    assert sha, 'native sha256sum required'
    (bin_dir / 'sha256sum').symlink_to(sha)
    curl = bin_dir / 'curl'
    curl.write_text('#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n if [ "$1" = -o ]; then cp "$FIXTURE_ARCHIVE" "$2"; exit $?; fi\n shift\ndone\nexit 2\n')
    curl.chmod(0o755)
    runner = tmp_path / 'runner'
    runner.mkdir()
    log = tmp_path / 'calls'
    bash = shutil.which('bash')
    assert bash
    result = subprocess.run([bash, '-c', script], cwd=tmp_path,
                            env={'PATH': str(bin_dir) + ':/usr/bin:/bin',
                                 'RUNNER_TEMP': str(runner), 'GITHUB_PATH': str(tmp_path / 'path'),
                                 'FIXTURE_ARCHIVE': str(archive), 'CALL_LOG': str(log)},
                            text=True, capture_output=True, timeout=30)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_checksum_mismatch_blocks_every_consumer(tmp_path):
    result, calls = run_installer(tmp_path, installer())
    assert result.returncode != 0, result.stdout + result.stderr
    assert calls == [], 'mismatch must cause zero tar/install/execution'
    assert not (tmp_path / 'path').exists()


def test_valid_archive_reaches_real_tar_install_and_fixture_exec(tmp_path):
    result, calls = run_installer(tmp_path, installer(), valid=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ['tar', 'install', 'exec']
    assert (tmp_path / 'path').read_text().strip() == str(tmp_path / 'runner/cargo-audit-bin')


@pytest.mark.parametrize('mutation', ['missing_check', 'late_check'])
def test_shell_negative_controls_detect_unverified_consumption(tmp_path, mutation):
    lines = installer().splitlines(keepends=True)
    check = next(line for line in lines if 'sha256sum --check' in line)
    lines.remove(check)
    if mutation == 'late_check':
        lines.append(check)
    result, calls = run_installer(tmp_path, ''.join(lines))
    assert calls == ['tar', 'install', 'exec'], 'fixture must detect premature consumption'
    assert result.returncode == (0 if mutation == 'missing_check' else 1)
