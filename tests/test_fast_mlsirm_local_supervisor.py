"""Real finite local actors; never GPU execution evidence."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.ci import fast_mlsirm_local_supervisor as m


def test_owned_finite_child_is_waited_before_release(tmp_path):
    owner = m.Supervisor(tmp_path)
    result = owner.run("success", timeout=2)
    assert result["status"] == "local_success"
    assert result["wait_returncode"] == 0
    assert result["pid"] > 0
    assert result["hardware_admitted"] is False
    assert owner.child.returncode == 0
    assert owner.lock_fd is None
    assert json.loads((tmp_path / "settlement.json").read_text())["status"] == "local_success"


def test_child_failure_is_nonpassing_but_settled(tmp_path):
    owner = m.Supervisor(tmp_path)
    result = owner.run("failure", timeout=2)
    assert result["status"] == "child_failed"
    assert result["wait_returncode"] == 17
    assert owner.child.returncode == 17
    assert owner.lock_fd is None


def test_timeout_waits_original_child(tmp_path):
    owner = m.Supervisor(tmp_path)
    result = owner.run("stall", timeout=0.05)
    assert result["status"] == "timeout"
    assert type(owner.child.returncode) is int
    assert result["wait_returncode"] == owner.child.returncode
    assert owner.lock_fd is None


def lock_probe(root):
    """A different process opens its own descriptor: actual kernel contention."""
    p = subprocess.run([sys.executable, "-I", "-S", "-c", """
import fcntl,os,sys
fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)
try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError: sys.exit(9)
finally: os.close(fd)
""", str(root / "local.lock")], timeout=2)
    return p.returncode


def test_contended_lease_never_launches_child(tmp_path):
    fd = os.open(tmp_path / "local.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    owner = m.Supervisor(tmp_path)
    try:
        with pytest.raises(BlockingIOError):
            owner.run("success")
        assert owner.child is None
        assert owner.lock_fd is None
    finally:
        os.close(fd)
        if owner.lock_fd is not None:
            os.close(owner.lock_fd)


def test_cancellation_waits_original_child(tmp_path):
    import threading
    import time
    owner = m.Supervisor(tmp_path)
    cancel = threading.Event()
    def request():
        deadline = time.monotonic() + 2
        while owner.child is None and time.monotonic() < deadline:
            time.sleep(0.001)
        cancel.set()
    thread = threading.Thread(target=request)
    thread.start()
    try:
        result = owner.run("stall", timeout=2, cancel=cancel)
    finally:
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert result["status"] == "cancelled"
    assert type(owner.child.returncode) is int
    assert owner.lock_fd is None


def test_settlement_write_failure_keeps_lock_until_reconciled(tmp_path, monkeypatch):
    owner = m.Supervisor(tmp_path)
    original = m._atomic_write
    def fail(path, value):
        if path.name == "settlement.json":
            raise OSError("fixture journal refusal")
        return original(path, value)
    monkeypatch.setattr(m, "_atomic_write", fail)
    try:
        with pytest.raises(OSError, match="fixture journal refusal"):
            owner.run("success")
        assert owner.child.returncode == 0
        assert lock_probe(tmp_path) == 9
        monkeypatch.setattr(m, "_atomic_write", original)
        owner.reconcile()
        assert owner.lock_fd is None
        assert lock_probe(tmp_path) == 0
    finally:
        if owner.lock_fd is not None:
            os.close(owner.lock_fd)


def test_preexisting_uncertain_attempt_blocks_after_process_death(tmp_path):
    (tmp_path / "attempt.json").write_text('{"status":"unknown"}')
    owner = m.Supervisor(tmp_path)
    with pytest.raises(ValueError, match="attempt already exists"):
        owner.run("success")
    assert owner.child is None


@pytest.mark.parametrize("mode,timeout", [("native", 2), ("other", 2), ("success", True), ("success", float("nan")), ("success", 0), ("success", 20)])
def test_invalid_workload_never_acquires_or_spawns(tmp_path, mode, timeout):
    owner = m.Supervisor(tmp_path)
    with pytest.raises(ValueError):
        owner.run(mode, timeout=timeout)
    assert owner.child is None
    assert list(tmp_path.iterdir()) == []


def test_after_spawn_keyboard_interrupt_preserves_primary_and_wait(tmp_path, monkeypatch):
    owner = m.Supervisor(tmp_path)
    original = owner._wait
    interrupt = KeyboardInterrupt("fixture cancellation")
    count = 0
    def wait(timeout):
        nonlocal count
        count += 1
        if count == 1: raise interrupt
        return original(timeout)
    monkeypatch.setattr(owner, "_wait", wait)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.run("stall")
    assert caught.value is interrupt
    assert type(owner.child.returncode) is int
    assert owner.lock_fd is None
    assert json.loads((tmp_path / "settlement.json").read_text())["status"] == "interrupted"


def test_wait_uncertainty_retains_lock_and_blocks_relaunch(tmp_path, monkeypatch):
    owner = m.Supervisor(tmp_path)
    original = owner._wait
    def refuse(_): raise OSError("fixture wait refusal")
    monkeypatch.setattr(owner, "_wait", refuse)
    try:
        with pytest.raises(OSError, match="fixture wait refusal"):
            owner.run("stall")
        assert owner in m._UNRESOLVED
        assert lock_probe(tmp_path) == 9
        with pytest.raises(ValueError, match="single use"):
            owner.run("success")
        assert not (tmp_path / "settlement.json").exists()
    finally:
        monkeypatch.setattr(owner, "_wait", original)
        owner.reconcile()
    assert type(owner.child.returncode) is int
    assert lock_probe(tmp_path) == 0


def receipt_input(tmp_path, owner):
    """A read-only synthetic expectation; never a product build manifest."""
    import hashlib
    from tests.test_fast_mlsirm_receipts import fixture
    binding, _, _ = fixture()
    binding["lease"] = owner.token
    path = tmp_path / "input.json"
    value = json.dumps({"scope": "synthetic-local-only", "binding": binding}).encode()
    path.write_bytes(value)
    path.chmod(0o444)
    return path, hashlib.sha256(value).hexdigest(), binding


def test_owned_child_receipt_is_consumed_before_settlement(tmp_path):
    owner = m.Supervisor(tmp_path)
    path, digest, binding = receipt_input(tmp_path, owner)
    result = owner.run("receipt", input_path=path, input_sha256=digest, expected=binding)
    assert result["status"] == "local_success"
    assert result.get("receipt_validated") is True
    assert owner.child.returncode == 0
    assert owner.lock_fd is None
    assert result["hardware_admitted"] is False
    assert json.loads((tmp_path / "settlement.json").read_text())["receipt_validated"] is True


@pytest.mark.parametrize("attack", ["missing-digest", "wrong-digest", "writable", "symlink", "wrong-source", "wrong-run", "duplicate"])
def test_immutable_inputs_reject_before_lease(tmp_path, attack):
    import hashlib
    owner = m.Supervisor(tmp_path)
    path, digest, binding = receipt_input(tmp_path, owner)
    if attack == "missing-digest": digest = None
    if attack == "wrong-digest": digest = "0" * 64
    if attack == "writable": path.chmod(0o644)
    if attack == "symlink":
        alias = tmp_path / "alias.json"
        alias.symlink_to(path)
        path = alias
    if attack == "wrong-source": binding["source_sha"] = "f" * 40
    if attack == "wrong-run": binding["run_id"] = "999"
    if attack == "duplicate":
        value = path.read_bytes().replace(b'"scope":', b'"scope":"bad","scope":', 1)
        path.chmod(0o644); path.write_bytes(value); path.chmod(0o444)
        digest = hashlib.sha256(value).hexdigest()
    with pytest.raises((ValueError, OSError)):
        owner.run("receipt", input_path=path, input_sha256=digest, expected=binding)
    assert owner.child is None
    assert not (tmp_path / "local.lock").exists()


def test_receipt_rejection_flows_through_real_supervisor(tmp_path, monkeypatch):
    owner = m.Supervisor(tmp_path)
    path, digest, binding = receipt_input(tmp_path, owner)
    original = owner._wait
    def wait(timeout):
        code = original(timeout)
        report = tmp_path / "local-receipt.json"
        data = json.loads(report.read_text())
        data["calls"][0]["run_id"] = "999"
        report.write_text(json.dumps(data))
        return code
    monkeypatch.setattr(owner, "_wait", wait)
    result = owner.run("receipt", input_path=path, input_sha256=digest, expected=binding)
    assert result["status"] == "receipt_rejected"
    assert result["receipt_validated"] is False
    assert owner.child.returncode == 0
    assert owner.lock_fd is None


def test_lock_is_held_inside_actual_child_wait(tmp_path, monkeypatch):
    owner = m.Supervisor(tmp_path)
    original = owner._wait
    observations = []
    def wait(timeout):
        observations.append(lock_probe(tmp_path))
        return original(timeout)
    monkeypatch.setattr(owner, "_wait", wait)
    owner.run("success")
    assert observations and set(observations) == {9}
    assert lock_probe(tmp_path) == 0


def test_cli_executes_local_attempt(tmp_path):
    result = subprocess.run([sys.executable, "-m", "scripts.ci.fast_mlsirm_local_supervisor",
                             "local", "--root", str(tmp_path), "--mode", "success"],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "local_success"


def test_cli_native_activation_closed(tmp_path):
    result = subprocess.run([sys.executable, "-m", "scripts.ci.fast_mlsirm_local_supervisor",
                             "native", "--root", str(tmp_path)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("alias", ["root", "input-parent"])
def test_symlink_ancestor_never_admits(tmp_path, alias):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    owner = m.Supervisor(link if alias == "root" else real)
    path, digest, binding = receipt_input(real, owner)
    if alias == "input-parent": path = link / path.name
    with pytest.raises(ValueError, match="symlink"):
        owner.run("receipt", input_path=path, input_sha256=digest, expected=binding)
    assert owner.child is None


def test_failed_attempt_reservation_releases_unclaimed_lock(tmp_path):
    (tmp_path / "attempt.json").mkdir()
    owner = m.Supervisor(tmp_path)
    try:
        with pytest.raises((ValueError, OSError)):
            owner.run("success")
        assert owner.child is None
        assert owner.lock_fd is None
        assert lock_probe(tmp_path) == 0
    finally:
        if owner.lock_fd is not None: os.close(owner.lock_fd)


def test_lock_hardlink_cannot_split_authority(tmp_path):
    target = tmp_path / "foreign"
    target.write_bytes(b"untouched")
    os.link(target, tmp_path / "local.lock")
    owner = m.Supervisor(tmp_path)
    try:
        with pytest.raises(ValueError, match="lock identity"):
            owner.run("success")
        assert owner.child is None
        assert owner.lock_fd is None
        assert target.read_bytes() == b"untouched"
    finally:
        if owner.lock_fd is not None: os.close(owner.lock_fd)
