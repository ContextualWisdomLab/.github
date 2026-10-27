"""Offline finite local lifecycle, not an admitted GPU route.

Only the fixed, descendant-free diagnostic programs below may execute. This
module cannot launch pytest, GPU code, arbitrary argv or an Actions runner.
"""
import argparse
import fcntl
import stat
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from scripts.ci.review_admission_controller import _atomic_write, _open_regular_nofollow
from scripts.ci import fast_mlsirm_receipts as receipts

# Strong custody on uncertainty: never rely on Popen.__del__ or reconstruct a PID.
_UNRESOLVED = set()
_PROGRAMS = {
    "success": "pass",
    "receipt": """import hashlib,json,os,sys,xml.etree.ElementTree as E
# Fixed synthetic-only producer; does not import pytest or product code.
binding=json.loads(sys.argv[1]); cases=json.loads(sys.argv[2])
suite=E.Element('testsuite',tests='3',failures='0',errors='0',skipped='0')
props=E.SubElement(suite,'properties')
for key,value in binding.items(): E.SubElement(props,'property',name=key,value=str(value))
calls=[]
for index,node in enumerate(cases):
    file,name=node.split('::'); call_id=hashlib.sha256((binding['lease']+node).encode()).hexdigest()[:32]
    calls.append(dict(nodeid=node,call_id=call_id,outcome='passed',**binding))
    case=E.SubElement(suite,'testcase',classname=file[:-3].replace('/','.'),name=name)
    p=E.SubElement(case,'properties')
    E.SubElement(p,'property',name='nodeid',value=node)
    E.SubElement(p,'property',name='call_id',value=call_id)
xml=E.tostring(suite)
receipt=json.dumps(dict(schema='local-exact3-v1',scope='synthetic-local-only',binding=binding,calls=calls,junit_sha256=hashlib.sha256(xml).hexdigest())).encode()
for name,value in [('local-junit.xml',xml),('local-receipt.json',receipt)]:
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f: f.write(value); f.flush(); os.fsync(f.fileno())
""",
    "failure": "raise SystemExit(17)",
    "stall": "import time; time.sleep(1)",
}


def _no_symlink(path):
    """Reject lexical traversal and every existing symlink ancestor, without resolving."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("parent traversal forbidden")
    path = path.absolute()
    for component in (path, *path.parents):
        if stat.S_ISLNK(component.lstat().st_mode):
            raise ValueError("symlink path forbidden")
    return path


def _read_bound(path, digest=None, readonly=False):
    """Read one no-follow regular bounded snapshot; caller owns ancestor custody."""
    path = _no_symlink(path)
    fd = _open_regular_nofollow(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_nlink != 1 or before.st_size > 65536 or (readonly and before.st_mode & 0o222):
            raise ValueError("input must be bounded, single-link and read-only")
        value = stream.read(65537)
        after = os.fstat(stream.fileno())
    if before != after or len(value) > 65536:
        raise ValueError("input changed while reading")
    if digest is not None and (type(digest) is not str or hashlib.sha256(value).hexdigest() != digest):
        raise ValueError("immutable input digest mismatch")
    return value


class Supervisor:
    """Own one finite diagnostic child, kernel lock and durable attempt fence."""

    def __init__(self, root):
        """Use a caller-owned quiescent private directory, never a GPU lock."""
        self.root = Path(root)
        self.lock_fd = None
        self.child = None
        self.result = None
        self.token = uuid.uuid4().hex
        self.claimed = False
        self.waited = False
        self.secondary = []

    def _finish(self):
        """Persist exact original wait before lock retirement; failed I/O retains it."""
        if not self.waited or self.result is None:
            raise ValueError("original child settlement unknown")
        _atomic_write(self.root / "settlement.json", json.dumps(self.result, sort_keys=True))
        # Do not unlink/replace the lock inode. An ambiguous close is not retried.
        fd, self.lock_fd = self.lock_fd, None
        os.close(fd)
        _UNRESOLVED.discard(self)
        return dict(self.result)

    def _wait(self, timeout):
        """Accept only the original Popen's matching, exact integer wait result."""
        code = self.child.wait(timeout=timeout)
        if type(code) is not int or type(self.child.returncode) is not int or code != self.child.returncode:
            raise ValueError("original wait mismatch")
        self.waited = True
        return code

    def _drain(self):
        """Attempt signal and exact wait independently, retaining any uncertainty."""
        try:
            # kill() uses this live owned handle, never a disk PID or a reaped PGID.
            self.child.kill()
        except BaseException as error:
            self.secondary.append(error)
        return self._wait(2)

    def reconcile(self):
        """Retry journal persistence only in the same surviving owner; never relaunch."""
        if self.lock_fd is None or not self.claimed or self.result is None:
            raise ValueError("no retained attempt")
        if not self.waited:
            self.result["wait_returncode"] = self._wait(2)
        return self._finish()

    def run(self, mode, timeout=2, cancel=None, input_path=None, input_sha256=None, expected=None):
        """Hold local flock across spawn, cancellation, exact wait and journal fsync."""
        if self.claimed or self.child is not None or self.lock_fd is not None:
            raise ValueError("owner is single use")
        if type(mode) is not str or mode not in _PROGRAMS:
            raise ValueError("only fixed local workloads are admitted; native adapter missing")
        if not (type(timeout) is int or type(timeout) is float) or not 0 < timeout <= 5:
            raise ValueError("finite local timeout must be in (0, 5]")
        self.root = _no_symlink(self.root)
        binding = None
        if mode == "receipt":
            if type(input_sha256) is not str or len(input_sha256) != 64 or input_path is None:
                raise ValueError("immutable input digest required")
            receipts._binding(expected)
            binding = dict(expected)
            if binding["lease"] != self.token:
                raise ValueError("input lease is not this owner")
            payload = json.loads(_read_bound(input_path, input_sha256, readonly=True),
                                 object_pairs_hook=receipts._object)
            if type(payload) is not dict or set(payload) != {"scope", "binding"} or payload["scope"] != "synthetic-local-only":
                raise ValueError("local input shape invalid")
            receipts._binding(payload["binding"])
            if payload["binding"] != binding:
                raise ValueError("immutable expectation mismatch")
        self.lock_fd = _open_regular_nofollow(
            self.root / "local.lock", os.O_RDWR | os.O_CREAT | os.O_NONBLOCK
        )
        try:
            info = os.fstat(self.lock_fd)
            if info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError("lock identity invalid")
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            fd, self.lock_fd = self.lock_fd, None
            os.close(fd)
            raise
        try:
            fd = _open_regular_nofollow(
                self.root / "attempt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL
            )
        except FileExistsError:
            fd, self.lock_fd = self.lock_fd, None
            os.close(fd)
            raise ValueError("attempt already exists; explicit owner recovery required") from None
        except BaseException:
            fd, self.lock_fd = self.lock_fd, None
            os.close(fd)
            raise
        self.claimed = True
        _UNRESOLVED.add(self)
        # Existence is a durable deny fence even if the following write fails.
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"token": self.token, "status": "claimed", "scope": "local-only"}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        status, code = "settlement_unknown", None
        primary = None
        try:
            self.child = subprocess.Popen(
                [sys.executable, "-I", "-S", "-c", _PROGRAMS[mode]] +
                ([json.dumps(binding), json.dumps(receipts.CASES)] if binding else []),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True, env={}, cwd=self.root,
            )
            deadline = time.monotonic() + timeout
            while True:
                if cancel is not None and cancel.is_set():
                    status = "cancelled"
                    code = self._drain()
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timeout"
                    code = self._drain()
                    break
                try:
                    code = self._wait(min(remaining, 0.02))
                    status = "local_success" if code == 0 else "child_failed"
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as error:
            primary = error
            status = "interrupted"
            if self.child is not None and not self.waited:
                try:
                    code = self._drain()
                except BaseException as cleanup:
                    self.secondary.append(cleanup)
        self.result = {"status": status, "wait_returncode": code,
                       "pid": self.child.pid if self.child is not None else None,
                       "token": self.token, "hardware_admitted": False,
                       "scope": "local-only"}
        if primary is not None:
            if self.waited:
                try:
                    self._finish()
                except BaseException as cleanup:
                    self.secondary.append(cleanup)
            raise primary
        if binding is not None and status == "local_success":
            try:
                receipts.validate(_read_bound(self.root / "local-receipt.json"),
                                  _read_bound(self.root / "local-junit.xml"), binding)
                self.result["receipt_validated"] = True
            except (ValueError, OSError):
                self.result["status"] = "receipt_rejected"
                self.result["receipt_validated"] = False
        return self._finish()


def main(argv=None):
    """Expose only finite local diagnostics, with native activation absent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=("local",))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("success", "failure", "stall"), default="success")
    parser.add_argument("--timeout", type=float, default=2)
    args = parser.parse_args(argv)
    try:
        result = Supervisor(args.root).run(args.mode, timeout=args.timeout)
    except (ValueError, OSError):
        print("LOCAL_ATTEMPT_REJECTED; retain attempt fence for owner recovery", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "local_success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
