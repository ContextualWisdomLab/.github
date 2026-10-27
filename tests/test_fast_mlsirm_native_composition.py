"""New seam composition controls; all GPU records here are synthetic."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_fast_mlsirm_native_producer import ROOT, binding, envelope, module


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts/ci'/f'{name}.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_fixed_entrypoint_real_pytest_hooks_synthetic_core(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    e = load('fast_mlsirm_native_entrypoint')
    m = module()
    expected = envelope(m)
    class Core:
        def __init__(self): self.index = -1
        def ci_begin_native_scope(self, b):
            assert b == binding(); self.index += 1
            return expected['cases'][self.index]['call_id']
        def ci_end_native_scope(self, call):
            row = expected['cases'][self.index]
            assert row['call_id'] == call
            return row['native']
    p = e.NativeCases(Core(), binding())
    # Exercise real pytest hook delivery on inert cases, not numerical tests.
    file = tmp_path/'test_inert.py'
    file.write_text('def test_one(): pass\ndef test_two(): pass\ndef test_three(): pass\n')
    original_cases = e.CASES
    e.CASES = tuple('test_inert.py::test_'+x for x in ('one','two','three'))
    code = pytest.main(['-q', '-c', '/dev/null', '--rootdir='+str(tmp_path), '-p', 'no:cacheprovider', str(file)], plugins=[p])
    assert code == 0 and len(p.rows) == 3
    for row, node in zip(p.rows, original_cases): row['nodeid'] = node
    assert m.validate_native(dict(schema='native-exact3-v1', binding=binding(), cases=p.rows), binding()) == m.CASES


def test_entrypoint_no_native_api_is_refusal(tmp_path, monkeypatch):
    e = load('fast_mlsirm_native_entrypoint')
    p = e.NativeCases(SimpleNamespace(), binding())
    with pytest.raises(AttributeError): p.pytest_runtest_setup(SimpleNamespace(nodeid=e.CASES[0]))


def test_scope_collection_does_not_accept_skip_extra_or_missing():
    e = load('fast_mlsirm_native_entrypoint')
    p = e.NativeCases(None, binding())
    with pytest.raises(ValueError): p.pytest_collection_finish(SimpleNamespace(items=[]))
    p.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=n) for n in e.CASES]))


def test_gate_real_consumer_with_offline_protected_transport(tmp_path, monkeypatch):
    g = load('fast_mlsirm_native_gate'); m = module()
    # Only filesystem custody is faked. Real schema/run/dependency consumers run.
    files = {'expected.json':binding(), 'native.json':envelope(m),
             'settlement.json':dict(binding=binding(), status='success')}
    monkeypatch.setattr(g, 'protected_json', lambda p: files[p.name])
    # F1 containment: real consumers accept the identity chain, then refuse
    # native success because protected JSON is not authentication.
    with pytest.raises(ValueError, match='native provenance unavailable'):
        g.gate(tmp_path, '123', '1', 'a'*40)
    for field, val in [('run_id','124'), ('source_sha','f'*40), ('attempt',2)]:
        original = files['expected.json'][field]; files['expected.json'][field] = val
        with pytest.raises(ValueError): g.gate(tmp_path, '123', '1', 'a'*40)
        files['expected.json'][field] = original
    for broken in ({'status': 'success'}, {'binding': binding()}, [], dict(binding=binding(), status='success', extra=1)):
        original = files['settlement.json']; files['settlement.json'] = broken
        with pytest.raises(ValueError, match='settlement shape invalid'): g.gate(tmp_path, '123', '1', 'a'*40)
        files['settlement.json'] = original
    files.pop('native.json')
    with pytest.raises(KeyError): g.gate(tmp_path, '123', '1', 'a'*40)


def test_native_settlement_actual_wait_owned_inert_process(tmp_path):
    m = module()
    # Fake cgroup files, REAL original Popen wait. Not native kernel containment.
    scope = tmp_path/'scope'; scope.mkdir()
    (scope/'cgroup.kill').write_text('')
    (scope/'cgroup.events').write_text('populated 0\n')
    t = object.__new__(m.LinuxTransport)
    t.scope = scope; t.launch_attempted = True
    t.child = subprocess.Popen([sys.executable, '-I', '-c', 'pass'], start_new_session=True)
    t.child.wait(timeout=5)
    # cgroup files are virtual on Linux; remove fake files only on rmdir.
    old = Path.rmdir
    from unittest.mock import patch
    def rmdir(p):
        (p/'cgroup.kill').unlink(); (p/'cgroup.events').unlink(); old(p)
    import time
    with patch.object(Path, 'rmdir', rmdir): t.settle(time.monotonic()+5)
    assert t.child.returncode == 0 and t.scope is None


def test_workflow_seam_and_unchanged_software_jobs():
    import yaml
    path = '.github/workflows/fast-mlsirm-ci.yml'
    current = yaml.safe_load((ROOT/path).read_text())
    baseline = yaml.safe_load(subprocess.check_output(['git','show','b4f1cb6837a2aa795e7d0b2c3a949d7213a488f3:'+path],cwd=ROOT))
    for job in ('python-matrix','rust','gpu-smoke','fuzz','package'):
        assert current['jobs'][job] == baseline['jobs'][job]
    gate = current['jobs']['python']
    assert gate['if'] == '${{ always() }}'
    assert gate['needs'] == ['python-matrix', 'gpu-smoke']
    step = gate['steps'][-1]
    assert step['if'] == '${{ always() }}'
    assert '/opt/cwlab/fast-mlsirm-native/fast_mlsirm_native_gate.py' in step['run']
    assert 'exit 1' not in step['run']
    assert set(current['jobs']) == set(baseline['jobs'])
