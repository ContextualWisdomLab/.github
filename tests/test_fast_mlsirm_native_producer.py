"""Offline synthetic Linux/GPU transport; never native admission evidence."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/ci'))


def module():
    spec = importlib.util.spec_from_file_location('native_producer', ROOT / 'scripts/ci/fast_mlsirm_native_producer.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def binding():
    return dict(source_sha='a'*40, extension_sha256='b'*64, supplier_sha='c'*40,
                run_id='123', attempt=1, job='native', lease='d'*32,
                generation='boot:inode', device='0000:01:00.0')


def envelope(m):
    b = binding()
    return dict(schema='native-exact3-v1', binding=b, cases=[dict(
        nodeid=n, outcome='passed', call_id=f'{i+1:032x}',
        native=dict(binding=b, call_id=f'{i+1:032x}', complete=True,
                    dispatches=[dict(backend='vulkan', adapter=b['device'],
                                     device_type='discrete', gpu_used=True,
                                     fallback_reason=None, phase='terminal', sequence=0)]))
        for i, n in enumerate(m.CASES)])


def trusted_ancestors(monkeypatch, root):
    """Synthetic metadata ONLY for host directories above the fixture-owned root.

    The lease root and everything below it keep real lstat metadata, so symlink,
    owner and mode checks on fixture paths remain real.
    """
    real = Path.lstat
    def lstat(p, *a, **kw):
        st = real(p, *a, **kw)
        if Path(p) == root or root in Path(p).parents:
            return st
        values = list(st); values[4] = 0; values[0] &= ~0o022
        return os.stat_result(values)
    monkeypatch.setattr(Path, 'lstat', lstat)


class SyntheticTransport:
    """Recording fake; its positives do NOT establish Linux containment."""
    def __init__(self, data, fault=None, lease_root=None):
        self.data, self.fault, self.events = data, fault, []
        # F4 coupling contract: transport binding and lease root are checked
        # against the expected binding and the lease before any effect.
        self.binding = binding(); self.config = {'lease_root': str(lease_root)}
    def prepare(self):
        self.events.append('prepare')
    def start(self):
        self.events.append('start')
        if self.fault == 'launch':
            raise OSError('unknown launch')
    def wait(self, deadline, cancelled):
        self.events.append('wait')
        if self.fault == 'interrupt':
            raise KeyboardInterrupt()
        if self.fault == 'timeout':
            raise TimeoutError()
        if self.fault == 'wait':
            raise OSError('unknown wait')
        return (None if self.fault == 'missing_exit' else 42 if self.fault == 'nonzero' else 0), json.dumps(self.data).encode()
    def settle(self, deadline):
        self.events.append('settle')
        if self.fault in ('cleanup', 'launch', 'wait', 'missing_exit'):
            raise OSError('unsettled')
    def close(self):
        self.events.append('close')


def test_same_call_positive_synthetic():
    m = module()
    assert m.validate_native(envelope(m), binding()) == m.CASES


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'extra', 'skip', 'failed', 'source', 'run', 'gpu', 'software', 'fallback', 'empty', 'incomplete', 'adapter', 'duplicate_call', 'native_binding', 'no_terminal'])
def test_same_call_refuses(mutation):
    m = module()
    e = envelope(m)
    row = e['cases'][0]
    if mutation == 'missing': e['cases'].pop()
    elif mutation == 'duplicate': e['cases'][1] = copy.deepcopy(row)
    elif mutation == 'extra': e['cases'].append(copy.deepcopy(row))
    elif mutation in ('skip', 'failed'): row['outcome'] = mutation
    elif mutation == 'source': e['binding']['source_sha'] = 'e'*40
    elif mutation == 'run': e['binding']['run_id'] = '999'
    elif mutation == 'gpu': row['native']['dispatches'][0]['gpu_used'] = False
    elif mutation == 'software': row['native']['dispatches'][0]['device_type'] = 'cpu'
    elif mutation == 'fallback': row['native']['dispatches'][0]['fallback_reason'] = 'fallback'
    elif mutation == 'empty': row['native']['dispatches'] = []
    elif mutation == 'incomplete': row['native']['complete'] = False
    elif mutation == 'adapter': row['native']['dispatches'][0]['adapter'] = 'other'
    elif mutation == 'duplicate_call': e['cases'][1]['call_id'] = row['call_id']
    elif mutation == 'native_binding': row['native']['binding'] = {}
    elif mutation == 'no_terminal': row['native']['dispatches'][0]['phase'] = 'start'
    with pytest.raises(ValueError): m.validate_native(e, binding())


def test_real_flock_excludes_competitor_and_poison_survives(tmp_path):
    m = module()
    a = m.DeviceLease(tmp_path, binding())
    a.acquire()
    with pytest.raises((BlockingIOError, ValueError)): m.DeviceLease(tmp_path, binding()).acquire()
    a.close()  # uncertainty is durable, not an automatically released lease
    with pytest.raises(ValueError, match='unsettled'): m.DeviceLease(tmp_path, binding()).acquire()


def test_real_flock_release_only_after_settlement(tmp_path):
    m = module()
    a = m.DeviceLease(tmp_path, binding()); a.acquire(); a.release(); a.close()
    b = m.DeviceLease(tmp_path, binding()); b.acquire(); b.release(); b.close()


@pytest.mark.parametrize('fault', [None, 'nonzero', 'timeout', 'interrupt', 'launch', 'wait', 'missing_exit', 'cleanup'])
def test_original_wait_and_lease_lifecycle_synthetic(tmp_path, monkeypatch, fault):
    m = module(); t = SyntheticTransport(envelope(m), fault, tmp_path)
    trusted_ancestors(monkeypatch, tmp_path)
    if fault is None:
        # F1 containment: a well-formed exact3 envelope from child stdout is
        # never native success, even after a clean settle/close/release.
        with pytest.raises(ValueError, match='native provenance unavailable'):
            m.produce(t, m.DeviceLease(tmp_path, binding()), binding(), time.monotonic()+5, lambda: False)
        assert t.events == ['prepare', 'start', 'wait', 'settle', 'close'] and t.cleanup_errors == ()
    else:
        with pytest.raises(BaseException):
            m.produce(t, m.DeviceLease(tmp_path, binding()), binding(), time.monotonic()+5, lambda: False)
    assert t.events[-1] == 'close'
    assert 'settle' in t.events
    lease = m.DeviceLease(tmp_path, binding())
    if fault in ('cleanup', 'launch', 'wait', 'missing_exit'):
        with pytest.raises(ValueError, match='unsettled'): lease.acquire()
    else:
        lease.acquire(); lease.release(); lease.close()


def test_stale_generation_refused_before_launch(tmp_path):
    m = module()
    with pytest.raises(ValueError, match='generation'):
        m.require_generation(binding(), 'other')


def test_linux_command_has_enforced_namespace_topology(tmp_path):
    m = module()
    argv = m.namespace_argv('/usr/bin/bwrap', '/image', '/checkout', '/supplier',
                            ['/dev/dri/renderD128'], 1001, 1001)
    assert argv[:3] == ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent']
    assert '--new-session' in argv and '--cap-drop' in argv
    assert argv[argv.index('--ro-bind')+1:argv.index('--ro-bind')+3] == ['/image', '/']
    assert '--dev' in argv and '--proc' in argv
    assert '--share-pid' not in argv and '--share-user' not in argv
    assert argv[-3:] == ['/usr/bin/python3', '-I', '/supplier/fast_mlsirm_native_entrypoint.py']


def test_entrypoint_authentication_rejects_changed_bytes(tmp_path):
    m = module(); p = tmp_path/'entry'; p.write_bytes(b'entry')
    with pytest.raises(ValueError, match='digest'): m.authenticate(p, '0'*64)


def test_terminal_rejects_unsuccessful_dependency():
    m = module()
    for status in ('failure', 'cancelled', 'skipped', '', None):
        with pytest.raises(ValueError, match='not successful'): m.terminal(status, envelope(m), binding())
    # F1 containment: a successful dependency plus a valid envelope is still not
    # authenticated native provenance; the format check itself stays positive.
    assert m.validate_native(envelope(m), binding()) == m.CASES
    with pytest.raises(ValueError, match='native provenance unavailable'):
        m.terminal('success', envelope(m), binding())


def test_acquire_interruption_stays_primary_when_lease_close_fails(tmp_path, monkeypatch):
    m = module(); trusted_ancestors(monkeypatch, tmp_path)
    lease = m.DeviceLease(tmp_path, binding()); t = SyntheticTransport(envelope(m), None, tmp_path)
    primary, secondary = KeyboardInterrupt('acquire'), OSError('lease close')
    def sync(): raise primary
    lease._sync = sync
    held = []
    def close(fd):
        if fd == lease.fd: held.append(fd); raise secondary
        return os.close(fd)
    monkeypatch.setattr(m, 'os', SimpleNamespace(**{**os.__dict__, 'close': close}))
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            m.produce(t, lease, binding(), time.monotonic()+5, lambda: False)
        assert caught.value is primary and t.cleanup_errors == (secondary,)
        assert t.events == ['close'] and lease.marker.exists()
        assert lease in m.UNRESOLVED and lease.unresolved_fd == held[0] and lease.fd is None
        with pytest.raises(ValueError, match='unresolved'):
            m.produce(SyntheticTransport(envelope(m), None, tmp_path), m.DeviceLease(tmp_path, binding()),
                      binding(), time.monotonic()+5, lambda: False)
    finally:
        os.close(held[0])


def test_uncertain_lease_close_keeps_poison_and_blocks_next_launch(tmp_path, monkeypatch):
    m = module(); trusted_ancestors(monkeypatch, tmp_path)
    lease = m.DeviceLease(tmp_path, binding()); t = SyntheticTransport(envelope(m), None, tmp_path)
    secondary = OSError('close took effect but reported failure')
    def close(fd):
        if fd == lease.fd: os.close(fd); raise secondary
        return os.close(fd)
    monkeypatch.setattr(m, 'os', SimpleNamespace(**{**os.__dict__, 'close': close}))
    with pytest.raises(ValueError, match='native provenance unavailable'):
        m.produce(t, lease, binding(), time.monotonic()+5, lambda: False)
    assert t.cleanup_errors == (secondary,) and lease.marker.exists() and lease in m.UNRESOLVED
    with pytest.raises(ValueError, match='lease not owned'): lease.release()
    nxt = SyntheticTransport(envelope(m), None, tmp_path)
    with pytest.raises(ValueError, match='unresolved'):
        m.produce(nxt, m.DeviceLease(tmp_path, binding()), binding(), time.monotonic()+5, lambda: False)
    assert nxt.events == [] and lease.marker.exists()


def test_poison_cleared_only_after_confirmed_close(tmp_path, monkeypatch):
    m = module(); trusted_ancestors(monkeypatch, tmp_path)
    lease = m.DeviceLease(tmp_path, binding()); order = []
    real_close, real_release = lease.close, lease.release
    lease.close = lambda: (order.append(('close', lease.fd is not None, lease.marker.exists())), real_close())[1]
    lease.release = lambda: (order.append(('release', lease.fd is None, lease.marker.exists())), real_release())[1]
    with pytest.raises(ValueError, match='native provenance unavailable'):
        m.produce(SyntheticTransport(envelope(m), None, tmp_path), lease, binding(), time.monotonic()+5, lambda: False)
    assert order == [('close', True, True), ('release', True, True)] and not lease.marker.exists()
    assert not m.UNRESOLVED


@pytest.mark.parametrize('kind', ['symlink_root', 'symlink_ancestor', 'relative', 'writable'])
def test_lease_root_admission_precedes_any_lease_file(tmp_path, monkeypatch, kind):
    m = module(); trusted_ancestors(monkeypatch, tmp_path)
    target = tmp_path/'target'; target.mkdir(mode=0o700)
    if kind == 'symlink_root':
        root = tmp_path/'alias'; root.symlink_to(target, target_is_directory=True)
    elif kind == 'symlink_ancestor':
        (tmp_path/'alias').symlink_to(target, target_is_directory=True)
        (target/'leases').mkdir(mode=0o700); root = tmp_path/'alias'/'leases'
    elif kind == 'relative':
        monkeypatch.chdir(target); root = Path('.')
    else:
        target.chmod(0o777); root = target
    opened = []
    def open_(path, *a, **kw): opened.append(str(path)); return os.open(path, *a, **kw)
    monkeypatch.setattr(m, 'os', SimpleNamespace(**{**os.__dict__, 'open': open_}))
    lease = m.DeviceLease(root, binding()); t = SyntheticTransport(envelope(m), None, root)
    with pytest.raises(ValueError, match='lexical'):
        m.produce(t, lease, binding(), time.monotonic()+5, lambda: False)
    assert not opened and not t.events and lease.fd is None
    assert sorted(p.name for p in target.iterdir()) == (['leases'] if kind == 'symlink_ancestor' else [])
    target.chmod(0o700)


def test_lexically_different_lease_root_is_refused_before_effects(tmp_path, monkeypatch):
    m = module(); trusted_ancestors(monkeypatch, tmp_path)
    (tmp_path/'alias').symlink_to(tmp_path, target_is_directory=True)
    lease = m.DeviceLease(tmp_path, binding()); t = SyntheticTransport(envelope(m), None, tmp_path/'alias')
    with pytest.raises(ValueError, match='root mismatch'):
        m.produce(t, lease, binding(), time.monotonic()+5, lambda: False)
    assert not t.events and not lease.path.exists() and not lease.marker.exists()
