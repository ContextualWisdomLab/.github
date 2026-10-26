"""Enroll the published source-only scanner tools in the root pytest/100% gate.

All archive payloads are synthetic. These tests do not acquire inventories,
execute real scanners, build an image, activate workflows, or use credentials.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import sys
import tarfile
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 repository contract
    import tomli as tomllib
import unittest
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'infra/security-scanners'


def load_source(name):
    """Import one actual published module under a distinct local name."""
    spec = importlib.util.spec_from_file_location('scanner_' + name, SOURCE / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ADAPTER = load_source('adapter')
ACQUIRE = load_source('acquire_tools')


def test_scanner_production_is_in_unchanged_100_percent_gate():
    """Both production tools must be measured, without narrowing scripts/ci."""
    config = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['coverage']
    assert config['run']['branch'] is True
    assert config['report']['fail_under'] == 100
    assert config['run']['source'] == ['scripts/ci', 'infra/security-scanners']
    assert config['run']['omit'] == [
        'tests/*', 'infra/security-scanners/test_adapter.py',
        'infra/security-scanners/parity_regressions.py',
        'infra/security-scanners/provenance_regressions.py',
    ]


ORIGINAL_CASES = [
    ('test_adapter', 'AdapterTests', name)
    for name in [
        'test_osv_scan_flags', 'test_retry', 'test_reporter', 'test_scorecard_scope',
        'test_trivy_flags', 'test_unknown', 'test_verify_rejects_tamper',
        'test_status_not_overwritten', 'test_no_docker',
    ]
] + [
    ('provenance_regressions', 'ExactArchiveAdmission', name)
    for name in [
        'test_exact_unique_regular_positive', 'test_wrong_path_same_basename_rejected',
        'test_duplicate_basename_rejected', 'test_duplicate_exact_path_rejected',
        'test_selected_symlink_rejected', 'test_parent_symlink_trap_rejected',
        'test_parent_hardlink_trap_rejected', 'test_traversal_rejected',
        'test_dot_alias_rejected', 'test_absolute_rejected',
        'test_content_digest_checked', 'test_missing_member_rejected',
    ]
] + [
    ('parity_regressions', 'ParityFindings', name)
    for name in [
        'test_F1_all_child_timeouts_remain_caller_owned',
        'test_F2_signalled_child_matches_pinned_wrapper',
    ]
]


@pytest.mark.parametrize('filename,classname,method', ORIGINAL_CASES,
                         ids=[row[2] for row in ORIGINAL_CASES])
def test_original_published_regression(filename, classname, method, tmp_path):
    """Run every retained original case through canonical tests/ discovery."""
    argv = [str(SOURCE / (filename + '.py')), str(SOURCE)]
    if filename == 'parity_regressions':
        argv += [str(SOURCE / 'exit_code_redirect.sh'), str(tmp_path)]
    with patch.object(sys, 'argv', argv), patch.dict(sys.modules, adapter=ADAPTER):
        namespace = runpy.run_path(str(SOURCE / (filename + '.py')))
        result = unittest.TestResult()
        namespace[classname](method).run(result)
    assert result.testsRun == 1
    assert not result.skipped
    assert result.wasSuccessful(), result.errors + result.failures


def archive(rows):
    """Create finite gzip/tar members, never external or installed artifacts."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as stream:
        for name, kind, content in rows:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            stream.addfile(member, io.BytesIO(content) if member.isreg() else None)
    return output.getvalue()


def descriptor(blob):
    """Describe only the finite synthetic bytes supplied by this test."""
    return {'size': len(blob), 'digest': 'sha256:' + ACQUIRE.sha(blob)}


def selection(blob, *, expected=None, diff_id=None):
    """Call the actual exact-member verifier, not a reimplementation."""
    return ACQUIRE.verified_members(
        blob, descriptor(blob), expected or {'tool': ('tool', ACQUIRE.sha(b'ok'), 8)}, diff_id)


@pytest.mark.parametrize('mutation', ['size-type', 'negative', 'large', 'digest-type', 'digest-format', 'size', 'hash'])
def test_descriptor_identity_rejected(mutation):
    """Reject each independent whole-artifact descriptor failure."""
    meta = descriptor(b'ok')
    if mutation == 'size-type': meta['size'] = True
    elif mutation == 'negative': meta['size'] = -1
    elif mutation == 'large': meta['size'] = ACQUIRE.MAX_ARCHIVE + 1
    elif mutation == 'digest-type': meta['digest'] = None
    elif mutation == 'digest-format': meta['digest'] = 'sha256:no'
    elif mutation == 'size': meta['size'] += 1
    else: meta['digest'] = 'sha256:' + '0' * 64
    with pytest.raises(ValueError, match='artifact identity mismatch'):
        ACQUIRE.verified_bytes(b'ok', meta)


def test_read_bounded_positive_and_refusals(tmp_path, monkeypatch):
    """Size admission and a growth-after-stat control remain fail closed."""
    path = tmp_path / 'artifact'
    path.write_bytes(b'ok')
    assert ACQUIRE.read_bounded(path, 2) == b'ok'
    link = tmp_path / 'link'
    link.symlink_to(path)
    for candidate, limit in [(link, 8), (tmp_path / 'absent', 8), (path, 1)]:
        with pytest.raises(ValueError, match='artifact file refused'):
            ACQUIRE.read_bounded(candidate, limit)
    original = Path.open
    def grow(selected, *args, **kwargs):
        return io.BytesIO(b'larger') if selected == path else original(selected, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', grow)
    with pytest.raises(ValueError, match='artifact size refused'):
        ACQUIRE.read_bounded(path, 2)


def test_member_limits_and_layer_identity(monkeypatch):
    """Exercise expanded bytes, member count, diff ID and valid no-digest member."""
    blob = archive([('tool', tarfile.REGTYPE, b'ok')])
    assert selection(blob, diff_id='sha256:' + ACQUIRE.sha(gzip.decompress(blob))) == {'tool': b'ok'}
    assert selection(blob, expected={'tool': ('tool', None, 8)}) == {'tool': b'ok'}
    with pytest.raises(ValueError, match='layer diff identity mismatch'):
        selection(blob, diff_id='sha256:' + '0' * 64)
    with monkeypatch.context() as small:
        small.setattr(ACQUIRE, 'MAX_EXPANDED', 1)
        with pytest.raises(ValueError, match='expanded archive limit'): selection(blob)
    with monkeypatch.context() as small:
        small.setattr(ACQUIRE, 'MAX_MEMBERS', 0)
        with pytest.raises(ValueError, match='archive member limit'): selection(blob)


@pytest.mark.parametrize('name,kind', [
    ('', tarfile.REGTYPE), ('/tool', tarfile.REGTYPE), ('x\\tool', tarfile.REGTYPE),
    ('x//tool', tarfile.REGTYPE), ('./tool', tarfile.REGTYPE),
    ('../tool', tarfile.REGTYPE), ('tool', tarfile.FIFOTYPE),
])
def test_unsafe_member_aliases_rejected(name, kind):
    """Never normalize aliases or special files into admitted members."""
    with pytest.raises(ValueError, match='unsafe or duplicate archive member'):
        selection(archive([(name, kind, b'ok')]))


def test_selected_member_and_output_refusals():
    """Reject directories, empty/oversized bodies, regular parents and output collisions."""
    for kind, content, limit in [(tarfile.DIRTYPE, b'', 8), (tarfile.REGTYPE, b'', 8), (tarfile.REGTYPE, b'ok', 1)]:
        with pytest.raises(ValueError, match='selected regular member refused'):
            selection(archive([('tool', kind, content)]), expected={'tool': ('tool', None, limit)})
    blob = archive([('parent', tarfile.REGTYPE, b'ok'), ('parent/tool', tarfile.REGTYPE, b'ok')])
    with pytest.raises(ValueError, match='archive parent is not a directory'):
        selection(blob, expected={'parent/tool': ('tool', None, 8)})
    blob = archive([('a', tarfile.REGTYPE, b'ok'), ('b', tarfile.REGTYPE, b'ok')])
    with pytest.raises(ValueError, match='duplicate output name'):
        selection(blob, expected={p: ('tool', None, 8) for p in ['a', 'b']})


def test_short_extracted_body_rejected(monkeypatch):
    """A truncated selected stream cannot satisfy the member-size fence."""
    blob = archive([('tool', tarfile.REGTYPE, b'ok')])
    monkeypatch.setattr(tarfile.TarFile, 'extractfile', lambda *args: io.BytesIO(b'o'))
    with pytest.raises(ValueError, match='member identity mismatch'): selection(blob)


def synthetic_recovery(tmp_path, monkeypatch):
    """Bind tiny test-owned manifests through the real complete recovery chain."""
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    blob = archive([('tool', tarfile.REGTYPE, b'ok')])
    (evidence / (ACQUIRE.sha(blob) + '.tar.gz')).write_bytes(blob)
    config = json.dumps({'os': 'linux', 'architecture': 'amd64',
                         'rootfs': {'diff_ids': ['sha256:' + ACQUIRE.sha(gzip.decompress(blob))]}}).encode()
    manifest = json.dumps({'config': descriptor(config), 'layers': [descriptor(blob)]}).encode()
    for name, data in [('fixture.manifest.raw.json', manifest), ('fixture.config.raw.json', config)]:
        (evidence / name).write_bytes(data)
    monkeypatch.setattr(ACQUIRE, 'IMAGES', {'fixture': (ACQUIRE.sha(manifest), {
        0: ('tool', 'tool', ACQUIRE.sha(b'ok'), 8)})})
    release = archive([('gitleaks', tarfile.REGTYPE, b'release')])
    monkeypatch.setattr(ACQUIRE, 'GITLEAKS_ARCHIVE', ACQUIRE.sha(release))
    monkeypatch.setattr(ACQUIRE, 'GITLEAKS_BINARY', ACQUIRE.sha(b'release'))
    (evidence / 'gitleaks_8.30.1_linux_x64.tar.gz').write_bytes(release)
    (evidence / 'gitleaks_8.30.1_checksums.txt').write_text(ACQUIRE.sha(release) + '  gitleaks_8.30.1_linux_x64.tar.gz\n')
    metadata = {'tag_name': 'v8.30.1', 'assets': [dict(name='gitleaks_8.30.1_linux_x64.tar.gz',
                    digest='sha256:' + ACQUIRE.sha(release), size=len(release), id=1)]}
    (evidence / 'gitleaks-v8.30.1-release.json').write_text(json.dumps(metadata))
    return evidence


def test_complete_synthetic_recovery_and_cli(tmp_path, monkeypatch, capsys):
    """Run successful recovery and CLI without reading the public inventory."""
    evidence = synthetic_recovery(tmp_path, monkeypatch)
    output = tmp_path / 'output'
    receipts = ACQUIRE.recover(evidence, output)
    assert len(receipts) == 2
    assert (output / 'tool').read_bytes() == b'ok'
    assert json.loads((output / 'inventory.json').read_text()) == {
        'tool': ACQUIRE.sha(b'ok'), 'gitleaks': ACQUIRE.sha(b'release')}
    assert (output / 'tool').stat().st_mode & 0o777 == 0o555
    # policy mode and upstream-wrapper inventory exclusion use authentic logic.
    monkeypatch.setattr(ACQUIRE, 'IMAGES', {'fixture': (ACQUIRE.IMAGES['fixture'][0], {
        0: ('tool', 'policy.yml', ACQUIRE.sha(b'ok'), 8)})})
    policy_output = tmp_path / 'policy-output'
    ACQUIRE.recover(evidence, policy_output)
    assert (policy_output / 'policy.yml').stat().st_mode & 0o777 == 0o444
    monkeypatch.setattr(ACQUIRE, 'IMAGES', {'fixture': (ACQUIRE.IMAGES['fixture'][0], {
        0: ('tool', 'exit_code_redirect.sh', ACQUIRE.sha(b'ok'), 8)})})
    with patch.object(sys, 'argv', ['acquire_tools', '--evidence', str(evidence), '--output', str(tmp_path / 'cli')]):
        ACQUIRE.main()
    assert json.loads(capsys.readouterr().out)['verified_members'] == 2
    assert 'exit_code_redirect.sh' not in json.loads((tmp_path / 'cli/inventory.json').read_text())
    with pytest.raises(FileExistsError): ACQUIRE.recover(evidence, output)


@pytest.mark.parametrize('mutation,reason', [
    ('manifest', 'manifest pin mismatch'), ('arch', 'image platform mismatch'),
    ('os', 'image platform mismatch'), ('overlap', 'duplicate recovered output'),
    ('checksums', 'release checksum transaction mismatch'),
    ('assets-count', 'release metadata mismatch'), ('asset-digest', 'release metadata mismatch'),
    ('tag', 'release metadata mismatch'),
])
def test_recovery_rejects_before_output(tmp_path, monkeypatch, mutation, reason):
    """Each failing complete-chain input must leave no output directory."""
    evidence = synthetic_recovery(tmp_path, monkeypatch)
    if mutation == 'manifest':
        (evidence / 'fixture.manifest.raw.json').write_bytes(b'{}')
    elif mutation in {'arch', 'os'}:
        config_path = evidence / 'fixture.config.raw.json'
        config = json.loads(config_path.read_text())
        config['architecture' if mutation == 'arch' else 'os'] = 'unadmitted'
        config_path.write_text(json.dumps(config))
        manifest_path = evidence / 'fixture.manifest.raw.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['config'] = descriptor(config_path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        monkeypatch.setattr(ACQUIRE, 'IMAGES', {'fixture': (ACQUIRE.sha(manifest_path.read_bytes()), ACQUIRE.IMAGES['fixture'][1])})
    elif mutation == 'overlap':
        pin, mapping = ACQUIRE.IMAGES['fixture']
        (evidence / 'second.manifest.raw.json').write_bytes((evidence / 'fixture.manifest.raw.json').read_bytes())
        (evidence / 'second.config.raw.json').write_bytes((evidence / 'fixture.config.raw.json').read_bytes())
        monkeypatch.setattr(ACQUIRE, 'IMAGES', {'fixture': (pin, mapping), 'second': (pin, mapping)})
    elif mutation == 'checksums':
        (evidence / 'gitleaks_8.30.1_checksums.txt').write_text('wrong\n')
    else:
        path = evidence / 'gitleaks-v8.30.1-release.json'
        metadata = json.loads(path.read_text())
        if mutation == 'assets-count': metadata['assets'] *= 2
        elif mutation == 'asset-digest': metadata['assets'][0]['digest'] = 'sha256:' + '0' * 64
        else: metadata['tag_name'] = 'unadmitted'
        path.write_text(json.dumps(metadata))
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match=reason): ACQUIRE.recover(evidence, output)
    assert not output.exists()


def test_real_acquisition_script_entry_refuses_absent_evidence(tmp_path):
    """The real __main__ branch must fail before output on absent input."""
    output = tmp_path / 'must-not-exist'
    with patch.object(sys, 'argv', ['acquire_tools', '--evidence', str(tmp_path / 'absent'), '--output', str(output)]):
        with pytest.raises(ValueError, match='artifact file refused'):
            runpy.run_path(str(SOURCE / 'acquire_tools.py'), run_name='__main__')
    assert not output.exists()


def test_real_adapter_script_entry_requires_owner_inventory(monkeypatch):
    """Exercise the real executable entry without a native installed scanner."""
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        if str(path) == '/opt/security/inventory.json':
            raise FileNotFoundError('fixture-only missing owner inventory')
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    with patch.object(sys, 'argv', ['adapter', 'osv-head']):
        with pytest.raises(FileNotFoundError, match='fixture-only missing owner inventory'):
            runpy.run_path(str(SOURCE / 'adapter.py'), run_name='__main__')


def test_adapter_integrity_privacy_signal_and_cli(tmp_path, monkeypatch):
    """Retain original status, required-inventory and secret-suppression boundaries."""
    tool = tmp_path / 'osv-scanner'
    tool.write_bytes(b'tool')
    digest = hashlib.sha256(tool.read_bytes()).hexdigest()
    ADAPTER.verify(tmp_path, {'osv-scanner': digest})
    with pytest.raises(ValueError, match='unknown inventory entry'): ADAPTER.verify(tmp_path, {'shell': digest})
    link = tmp_path / 'trivy'
    link.symlink_to(tool)
    with pytest.raises(ValueError, match='integrity failure'): ADAPTER.verify(tmp_path, {'trivy': digest})
    with pytest.raises(ValueError, match='integrity failure'): ADAPTER.verify(tmp_path, {'gitleaks': digest})
    with pytest.raises(ValueError, match='scanner absent'): ADAPTER.execute('trivy', tmp_path, {}, {})
    with patch.object(ADAPTER, 'verify'), patch.object(ADAPTER.subprocess, 'run') as run:
        for stage, returned, expected in [('osv-head', -15, 143), ('osv-report', 128, 128), ('scorecard', 1, 1)]:
            run.return_value.returncode = returned
            required = Path(ADAPTER.command(stage, tmp_path, {})[0][0]).name
            assert ADAPTER.execute(stage, tmp_path, {required: digest}, {}) == expected
            assert run.call_args.kwargs.get('timeout') is None
        assert run.call_args.kwargs['stdout'] == ADAPTER.subprocess.DEVNULL
        assert run.call_args.kwargs['stderr'] == ADAPTER.subprocess.DEVNULL
    # Patch fixed installation IO, not the production installation path.
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        return '{}' if str(path) == '/opt/security/inventory.json' else original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    with patch.object(sys, 'argv', ['adapter', 'osv-head']), patch.object(ADAPTER, 'execute', return_value=7) as execute:
        assert ADAPTER.main() == 7
        assert execute.call_args.args[:3] == ('osv-head', Path('/opt/security'), {})
