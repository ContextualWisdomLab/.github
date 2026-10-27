"""Linux native producer seam. Offline transports are NOT native evidence.

Deployment requires an independently admitted immutable image/checkout/supplier,
root-owned lease directory and delegated cgroup root, exclusive device assignment
and a current original controller. This module never provisions that authority.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from types import MappingProxyType

# Strong custody, not proof of reap. Any unresolved owner blocks further launches.
UNRESOLVED = []


def _errors(errors):
    if errors:
        primary = errors[0]
        for secondary in errors[1:]:
            BaseException.add_note(primary, 'secondary cleanup failure retained')
        raise primary


def native_binding(value):
    if type(value) is not dict or set(value) != BINDING | {'generation', 'device'}:
        raise ValueError('native binding shape')
    _binding({k: value[k] for k in BINDING})
    if any(type(value[k]) is not str or not value[k] for k in ('generation', 'device')):
        raise ValueError('native binding identity')
    return value

from fast_mlsirm_receipts import CASES, BINDING, _binding, _object

MAX_OUTPUT = 1024 * 1024


def authenticate(path, digest):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        raise ValueError('authenticated file digest mismatch')


_CONTROLLER_EUID = os.geteuid  # real syscall bound at import, not a test seam


def admitted_path(value, owners=(0,)):
    """Lexical + ancestor admission with NO filesystem effects (lstat only).

    Absolute, no '..', and for the path and every ancestor: not a symlink,
    owned by one of ``owners`` and not group/world writable.
    """
    p = Path(value)
    if not p.is_absolute() or '..' in p.parts:
        raise ValueError('absolute lexical admission path required')
    for parent in (p, *p.parents):
        st = parent.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid not in owners or st.st_mode & 0o022:
            raise ValueError('immutable lexical root-owned admission paths required')
    return p


def require_generation(binding, actual):
    if binding['generation'] != actual:
        raise ValueError('stale generation')


def validate_native(data, expected):
    native_binding(expected)
    if set(expected) != BINDING | {'generation', 'device'} or any(
            type(expected[k]) is not str or not expected[k] for k in ('generation', 'device')):
        raise ValueError('native binding shape')
    if type(data) is not dict or set(data) != {'schema', 'binding', 'cases'} or data['schema'] != 'native-exact3-v1' or data['binding'] != expected:
        raise ValueError('native envelope mismatch')
    native_binding(data['binding'])
    rows = data['cases']
    if type(rows) is not list or len(rows) != len(CASES):
        raise ValueError('exact3 required')
    nodes, calls = set(), set()
    for row in rows:
        if type(row) is not dict or set(row) != {'nodeid', 'outcome', 'call_id', 'native'}:
            raise ValueError('case shape')
        node, call = row['nodeid'], row['call_id']
        if node not in CASES or node in nodes or row['outcome'] != 'passed' or type(call) is not str or not re.fullmatch('[0-9a-f]{32}', call) or call in calls:
            raise ValueError('case identity/outcome')
        nodes.add(node); calls.add(call)
        native = row['native']
        if type(native) is not dict or set(native) != {'binding', 'call_id', 'complete', 'dispatches'} or native['binding'] != expected or native['call_id'] != call or native['complete'] is not True:
            raise ValueError('same-call native projection absent')
        native_binding(native['binding'])
        dispatches = native['dispatches']
        if type(dispatches) is not list or not 1 <= len(dispatches) <= 4096:
            raise ValueError('native dispatches absent/oversize')
        terminal_seen = False
        for i, d in enumerate(dispatches):
            if type(d) is not dict or set(d) != {'backend', 'adapter', 'device_type', 'gpu_used', 'fallback_reason', 'phase', 'sequence'}:
                raise ValueError('dispatch shape')
            if d['backend'] != 'vulkan' or d['adapter'] != expected['device'] or d['device_type'] not in ('discrete', 'integrated') or d['gpu_used'] is not True or d['fallback_reason'] is not None or type(d['sequence']) is not int or d['sequence'] != i or d['phase'] not in ('start', 'iteration', 'terminal'):
                raise ValueError('physical dispatch mismatch/refusal')
            terminal_seen |= d['phase'] == 'terminal'
        if not terminal_seen:
            raise ValueError('terminal numerical dispatch absent')
    return CASES


def terminal(status, data, expected):
    if status != 'success':
        raise ValueError('hardware dependency not successful')
    validate_native(data, expected)
    raise ValueError('native provenance unavailable: protected JSON is not authentication')


class DeviceLease:
    """Host-local flock plus durable poison: controller loss never frees admission.

    Root must be the independently provisioned device-global lock namespace, NOT
    a job directory in production. A leftover marker requires custodian recovery.
    """
    def __init__(self, root, binding):
        self.root, self.binding, self.fd = Path(root), dict(native_binding(binding)), None
        self.owned = False          # this object created the poison marker
        self.unresolved_fd = None   # close outcome unknown: never retried (FD reuse)
        self.cleanup_errors = ()
        key = hashlib.sha256(binding['device'].encode()).hexdigest()
        self.path = self.root / (key + '.lock')
        self.marker = self.root / (key + '.unsettled')

    def acquire(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(self.fd).st_mode):
                raise ValueError('lease is not regular')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.marker.exists() or self.marker.is_symlink():
                raise ValueError('unsettled previous device lease')
            fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, json.dumps(self.binding, sort_keys=True).encode()); os.fsync(fd)
            finally:
                os.close(fd)
            self.owned = True
            self._sync()
        except BaseException as primary:
            # Keep the acquisition interruption primary; a failed close is a
            # retained secondary and leaves this lease UNRESOLVED (poison kept).
            try:
                self.close()
            except BaseException as secondary:
                self.cleanup_errors = (secondary,)
                BaseException.add_note(primary, 'secondary lease close failure retained')
            raise

    def _sync(self):
        fd = os.open(self.root, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)

    def release(self):
        """Clear poison. Valid while held or after a CONFIRMED close only."""
        if not self.owned or self.unresolved_fd is not None or self in UNRESOLVED:
            raise ValueError('lease not owned')
        self.marker.unlink()
        self.owned = False
        self._sync()

    def close(self):
        if self.fd is None:
            return
        try:
            os.close(self.fd)
        except BaseException:
            # Outcome unknown (may or may not have taken effect): retain strong
            # custody, never retry the numeric FD, keep poison.
            self.unresolved_fd, self.fd = self.fd, None
            if self not in UNRESOLVED: UNRESOLVED.append(self)
            raise
        self.fd = None


def produce(transport, lease, binding, deadline, cancelled, cleanup_seconds=30):
    """Bounded diagnostic transport ONLY; no stdout can authorize native success.

    An authenticated out-of-address-space producer is not implemented. Even the
    ordinary synthetic entrypoint is rejected after capture and settlement.
    """
    native_binding(binding)
    if (native_binding(lease.binding) != binding or
            native_binding(transport.binding) != binding or
            Path(transport.config['lease_root']).resolve(strict=True) != lease.root.resolve(strict=True)):
        raise ValueError('lease/transport/expected binding or root mismatch')
    if UNRESOLVED:
        raise ValueError('unresolved original owner; no new launch')
    if not math.isfinite(deadline) or deadline <= time.monotonic() or not 0 < cleanup_seconds <= 120:
        raise ValueError('caller deadline/cleanup budget invalid')
    # Lease-root admission BEFORE the first lease file is created (no effects on
    # refusal). Lexical identity, not only resolved identity, must match; the
    # production transport additionally requires root-owned immutable ancestors.
    if Path(transport.config['lease_root']) != lease.root:
        raise ValueError('lease/transport/expected binding or root mismatch')
    # Owners: root or the controller's own euid (the Linux controller must be
    # euid 0, so production is root-only; prepare() re-checks root-only).
    admitted_path(lease.root, owners=(0, _CONTROLLER_EUID()))
    errors = []
    acquired = False
    settled = False
    try:
        try:
            lease.acquire()
        except BaseException:
            errors.extend(getattr(lease, 'cleanup_errors', ()))
            raise
        acquired = True
        transport.prepare()
        if cancelled(): raise InterruptedError('cancelled before launch')
        transport.start()
        code, raw = transport.wait(deadline, cancelled)
        if type(code) is not int: raise ValueError('original child exit missing')
        if code != 0: raise ValueError('numerical child failed')
        if len(raw) > MAX_OUTPUT: raise ValueError('receipt cap')
        data = json.loads(raw, object_pairs_hook=_object)
        validate_native(data, binding)
        raise ValueError('native provenance unavailable: child stdout is untrusted')
    except BaseException as error:
        errors.insert(0, error)
    finally:
        if acquired:
            try:
                transport.settle(time.monotonic() + cleanup_seconds)
                settled = True
            except BaseException as error:
                errors.append(error)
                if transport not in UNRESOLVED: UNRESOLVED.append(transport)
        try: transport.close()
        except BaseException as error: errors.append(error)
        lease_closed = False
        try:
            lease.close()
            lease_closed = True
        except BaseException as error:
            errors.append(error)
            if lease not in UNRESOLVED: UNRESOLVED.append(lease)
        # Poison is cleared only after settlement AND confirmed transport and
        # lease closure with no cleanup error; otherwise it stays durable.
        if acquired and settled and lease_closed and len(errors) == 1:
            try: lease.release()
            except BaseException as error:
                errors.append(error)
                if lease not in UNRESOLVED: UNRESOLVED.append(lease)
    transport.cleanup_errors = tuple(errors[1:])
    _errors(errors)


def namespace_argv(bwrap, image, checkout, supplier, devices, uid, gid):
    argv = [bwrap, '--unshare-all', '--die-with-parent', '--new-session',
            '--ro-bind', image, '/', '--ro-bind', checkout, '/checkout',
            '--ro-bind', supplier, '/supplier', '--proc', '/proc', '--dev', '/dev',
            '--tmpfs', '/tmp', '--dir', '/work', '--chdir', '/work',
            '--clearenv', '--setenv', 'PATH', '/usr/bin', '--setenv', 'STAGE5_HIGH_Q', '1',
            '--setenv', 'STAGE5_HIGH_Q_BOOTSTRAP_REPS', '2',
            '--setenv', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1',
            '--uid', str(uid), '--gid', str(gid), '--cap-drop', 'ALL']
    for device in devices:
        argv += ['--dev-bind', device, device]
    return argv + ['/usr/bin/python3', '-I', '/supplier/fast_mlsirm_native_entrypoint.py']


class LinuxTransport:
    """Original Popen owner, bounded capture, cgroup-v2 kill+empty settlement.

    PID/user/mount/network namespaces constrain supported descendant topology;
    no writable cgroup mount or host process namespace is exposed to tests.
    cgroup memory/pids bounds are caller policy; there is no science-time cap.
    """
    def __init__(self, *, cgroup_root, lease_root, image, checkout, supplier,
                 extension, binding, entry_sha256, launcher_sha256, bwrap_sha256,
                 memory_max, pids_max, devices, uid, gid):
        self.config = locals().copy(); self.config.pop('self')
        self.binding = dict(native_binding(binding)); self.child = None; self.scope = None
        self.output = bytearray(); self.selector = None; self.launch_attempted = False

    def prepare(self):
        c = self.config
        if sys.platform != 'linux' or os.geteuid() != 0 or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
            raise ValueError('Linux root controller/default wait policy required')
        c = dict(c)
        for key in ('cgroup_root', 'lease_root', 'image', 'checkout', 'supplier', 'extension'):
            c[key] = str(admitted_path(c[key]).resolve(strict=True))
        c['devices'] = tuple(c['devices'])
        self.config = MappingProxyType(c)
        root = Path(c['cgroup_root'])
        generation = Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + str(root.stat().st_ino)
        require_generation(self.binding, generation)
        authenticate(Path(c['supplier'])/'fast_mlsirm_native_entrypoint.py', c['entry_sha256'])
        authenticate(Path(c['supplier'])/'fast_mlsirm_native_launch.py', c['launcher_sha256'])
        authenticate('/usr/bin/bwrap', c['bwrap_sha256'])
        authenticate(c['extension'], self.binding['extension_sha256'])
        supplier_sha = subprocess.check_output(['/usr/bin/git', '-C', c['supplier'], 'rev-parse', 'HEAD'], timeout=10, env={'PATH':'/usr/bin'}).decode().strip()
        supplier_dirty = subprocess.check_output(['/usr/bin/git', '-C', c['supplier'], 'status', '--porcelain', '--untracked-files=all'], timeout=10, env={'PATH':'/usr/bin'})
        if supplier_sha != self.binding['supplier_sha'] or supplier_dirty:
            raise ValueError('supplier identity mismatch')
        sha = subprocess.check_output(['/usr/bin/git', '-C', c['checkout'], 'rev-parse', 'HEAD'], timeout=10, env={'PATH':'/usr/bin'}).decode().strip()
        dirty = subprocess.check_output(['/usr/bin/git', '-C', c['checkout'], 'status', '--porcelain', '--untracked-files=all'], timeout=10, env={'PATH':'/usr/bin'})
        if sha != self.binding['source_sha'] or dirty:
            raise ValueError('checkout identity mismatch')
        if not (Path(c['extension']).resolve().is_relative_to(Path(c['image']).resolve())):
            raise ValueError('extension outside immutable image')
        if type(c['memory_max']) is not int or c['memory_max'] <= 0 or type(c['pids_max']) is not int or not 2 <= c['pids_max'] <= 4096 or c['uid'] <= 0 or c['gid'] <= 0:
            raise ValueError('resource/identity policy invalid')
        if not c['devices']: raise ValueError('device mapping absent')
        for device in c['devices']:
            if not re.fullmatch(r'/dev/dri/renderD[0-9]+', device) or not stat.S_ISCHR(os.stat(device).st_mode):
                raise ValueError('unsupported device topology')
            pci = (Path('/sys/class/drm')/Path(device).name/'device').resolve().name
            if pci != self.binding['device']: raise ValueError('device PCI mismatch')
        scope = root / self.binding['lease']
        scope.mkdir()  # ownership starts only after successful exclusive creation
        self.scope = scope
        (self.scope/'memory.max').write_text(str(c['memory_max']))
        (self.scope/'pids.max').write_text(str(c['pids_max']))
        (self.scope/'memory.oom.group').write_text('1')
        if not (self.scope/'cgroup.kill').exists(): raise ValueError('cgroup.kill unavailable')

    def start(self):
        c = self.config
        fd = os.open(self.scope/'cgroup.procs', os.O_WRONLY)
        self.launch_attempted = True
        try:
            argv = namespace_argv('/usr/bin/bwrap', c['image'], c['checkout'], c['supplier'], c['devices'], c['uid'], c['gid'])
            # Preallocate the actual Popen object before native admission. CPython
            # __init__ publishes its PID on this retained object. Constructor-side
            # ambiguity remains UNKNOWN (not an invented wait receipt).
            owner = subprocess.Popen.__new__(subprocess.Popen)
            self._launch_owner = owner
            owner.__init__([sys.executable, '-I', str(Path(c['supplier'])/'fast_mlsirm_native_launch.py'), str(fd), *argv],
                pass_fds=(fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env={'PATH':'/usr/bin'}, start_new_session=True)
            self.child = owner
        finally: os.close(fd)
        payload = dict(binding=self.binding)
        self.child.stdin.write(json.dumps(payload).encode()); self.child.stdin.close()
        os.set_blocking(self.child.stdout.fileno(), False)
        self.selector = selectors.DefaultSelector(); self.selector.register(self.child.stdout, selectors.EVENT_READ)

    def wait(self, deadline, cancelled):
        eof = False
        while not eof or self.child.poll() is None:
            if cancelled(): raise InterruptedError('cancelled')
            if time.monotonic() >= deadline: raise TimeoutError('caller deadline')
            for key, _ in self.selector.select(min(.1, max(0, deadline-time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    self.selector.unregister(key.fileobj); eof = True
                self.output.extend(chunk)
                if len(self.output) > MAX_OUTPUT: raise ValueError('output cap')
        return self.child.wait(timeout=max(.001, deadline-time.monotonic())), bytes(self.output)

    def settle(self, deadline):
        errors = []
        if self.child is None:
            owner = getattr(self, '_launch_owner', None)
            if owner is not None and getattr(owner, 'pid', None) is not None:
                self.child = owner
        try:
            if self.child is not None and self.child.poll() is None:
                try: os.killpg(self.child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        except BaseException as error: errors.append(error)
        try:
            if self.scope is not None:
                (self.scope/'cgroup.kill').write_text('1')
        except BaseException as error: errors.append(error)
        try:
            if self.launch_attempted and (self.child is None or self.scope is None):
                raise ValueError('unknown launch custody')
            if self.child is not None:
                code = self.child.wait(timeout=max(.001, deadline-time.monotonic()))
                if type(code) is not int or type(self.child.returncode) is not int or code != self.child.returncode:
                    raise ValueError('missing original exit')
        except BaseException as error: errors.append(error)
        try:
            if self.scope is not None:
                while True:
                    events = dict(line.split() for line in (self.scope/'cgroup.events').read_text().splitlines())
                    if events.get('populated') == '0': break
                    if time.monotonic() >= deadline: raise TimeoutError('containment unsettled')
                    time.sleep(.01)
        except BaseException as error: errors.append(error)
        self.settlement_errors = tuple(errors)
        if errors:
            if self not in UNRESOLVED: UNRESOLVED.append(self)
            _errors(errors)
        if self.scope is not None:
            self.scope.rmdir(); self.scope = None

    def close(self):
        errors = []
        resources = [self.selector]
        child = self.child or getattr(self, '_launch_owner', None)
        if child:
            resources += [getattr(child, 'stdin', None), getattr(child, 'stdout', None)]
        for resource in resources:
            if resource is not None:
                try: resource.close()
                except BaseException as error: errors.append(error)
        self.close_errors = tuple(errors)
        if errors:
            if self not in UNRESOLVED: UNRESOLVED.append(self)
            _errors(errors)
