"""Fixed exact3 pytest entrypoint inside the admitted Linux namespace only.

No arbitrary argv, environment-selected tests or generated GPU metadata.
The product's missing native scope API is an explicit prerequisite, not a fake.
"""
import contextlib
import hashlib
import json
from pathlib import Path
import sys

CASES = (
    'tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_and_parity',
    'tests/test_bifactor_gpu.py::test_bifactor_gpu_equivalence_multigroup',
    'tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_q121',
)


class NativeCases:
    def __init__(self, core, binding):
        self.core, self.binding = core, binding
        self.rows, self.reports, self.ids = [], {}, {}

    def pytest_collection_finish(self, session):
        if [item.nodeid for item in session.items] != list(CASES):
            raise ValueError('exact unchanged test collection required')

    def pytest_runtest_setup(self, item):
        # Native API allocates the call identity and binds a thread-local scope.
        # It must fail if another scope is live; Python does not make a GPU claim.
        self.ids[item.nodeid] = self.core.ci_begin_native_scope(self.binding)

    def pytest_runtest_logreport(self, report):
        phases = self.reports.setdefault(report.nodeid, {})
        if report.when in phases:
            raise ValueError('duplicate phase')
        phases[report.when] = report.outcome
        if report.when == 'teardown':
            native = self.core.ci_end_native_scope(self.ids[report.nodeid])
            self.rows.append(dict(nodeid=report.nodeid,
                outcome='passed' if phases == dict(setup='passed', call='passed', teardown='passed') else 'failed',
                call_id=self.ids[report.nodeid], native=native))


def main():
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536: raise ValueError('request cap')
    request = json.loads(raw)
    if set(request) != {'binding'}: raise ValueError('request shape')
    binding = request['binding']
    import fast_mlsirm._core as core
    if hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest() != binding['extension_sha256']:
        raise ValueError('loaded extension digest mismatch')
    if not callable(getattr(core, 'ci_begin_native_scope', None)) or not callable(getattr(core, 'ci_end_native_scope', None)):
        raise ValueError('actual native dispatch scope producer missing')
    import pytest
    plugin = NativeCases(core, binding)
    # Pytest output never shares the bounded JSON receipt channel.
    with contextlib.redirect_stdout(sys.stderr):
        code = pytest.main(['-q', '-c', '/dev/null', '--rootdir=/checkout',
                            '-p', 'no:cacheprovider', '--override-ini=addopts=',
                            *['/checkout/' + node for node in CASES]], plugins=[plugin])
    if code != 0: raise SystemExit(int(code))
    data = dict(schema='native-exact3-v1', binding=binding, cases=plugin.rows)
    encoded = json.dumps(data, separators=(',', ':'))
    if len(encoded.encode()) > 1024*1024: raise ValueError('receipt cap')
    print(encoded)


if __name__ == '__main__':
    main()
