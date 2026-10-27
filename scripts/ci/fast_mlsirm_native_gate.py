"""Existing workflow terminal seam to an admitted producer's protected spool.

Installed at /opt/cwlab/fast-mlsirm-native/ by the existing custodian ONLY after
independent admission. No installation or hardware dispatch is done by this CLI.
A missing deployment/receipt fails, not a hardcoded unconditional failure.
"""
import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fast_mlsirm_native_producer import terminal, native_binding
from fast_mlsirm_receipts import _object


def protected_json(path):
    path = Path(path)
    for parent in (path, *path.parents):
        st = parent.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('untrusted receipt custody')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('receipt must be regular')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != 0 or
                opened.st_mode & 0o022 or opened.st_nlink != 1 or
                (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('opened receipt custody mismatch')
        raw = bytearray()
        while len(raw) <= 1024*1024:
            chunk = os.read(fd, min(65536, 1024*1024+1-len(raw)))
            if not chunk: break
            raw.extend(chunk)
        after = os.fstat(fd)
        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('receipt changed while reading')
    finally:
        os.close(fd)
    if len(raw) > 1024*1024: raise ValueError('receipt cap')
    return json.loads(raw, object_pairs_hook=_object)


def gate(root, run, attempt, source):
    if not run.isdecimal() or not attempt.isdecimal() or len(source) != 40 or any(c not in '0123456789abcdef' for c in source):
        raise ValueError('workflow identity invalid')
    directory = Path(root) / run / attempt
    expected = protected_json(directory/'expected.json')
    native_binding(expected)
    if expected['run_id'] != run or expected['attempt'] != int(attempt) or expected['source_sha'] != source:
        raise ValueError('stale workflow identity')
    settlement = protected_json(directory/'settlement.json')
    if type(settlement) is not dict or set(settlement) != {'binding', 'status'}:
        raise ValueError('settlement shape invalid')
    native_binding(settlement['binding'])
    if settlement['binding'] != expected:
        raise ValueError('settlement binding mismatch')
    return terminal(settlement['status'], protected_json(directory/'native.json'), expected)


if __name__ == '__main__':
    if len(sys.argv) != 4: raise SystemExit('run attempt source required')
    gate('/var/lib/cwlab/fast-mlsirm-native/settled', *sys.argv[1:])
