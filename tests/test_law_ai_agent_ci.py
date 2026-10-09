"""Central law CI admission contracts; no consumer product source is copied here."""

from __future__ import annotations

import hashlib
import json
import os
import re
import textwrap
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/law-ai-agent-ci.yml"
HELPER = ROOT / "scripts/ci/law_ai_agent_ci.sh"
SHA = "a" * 40


def workflow():
    """Read YAML with BaseLoader so the GitHub `on` key remains a string."""
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def admission(tmp_path, *, event="push", repository="ContextualWisdomLab/law-ai-agent", **overrides):
    """Execute the actual pre-checkout admission with synthetic GitHub metadata."""
    payload = {"after": SHA, "ref": "refs/heads/main", "deleted": False}
    if event == "pull_request":
        payload = {"pull_request": {"head": {"sha": SHA, "repo": {"full_name": repository}},
                                    "base": {"ref": "main", "repo": {"full_name": repository}}}}
    payload.update(overrides.pop("payload", {}))
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload))
    env = {**os.environ, "CALLER_REPOSITORY": repository, "CALLER_EVENT": event,
           "CALLER_REF": "refs/heads/main", "SOURCE_SHA": SHA,
           "CENTRAL_REPOSITORY": "ContextualWisdomLab/.github", "CENTRAL_SHA": SHA,
           "CENTRAL_REF": f"ContextualWisdomLab/.github/.github/workflows/law-ai-agent-ci.yml@{SHA}",
           "GITHUB_EVENT_PATH": str(path), "GITHUB_OUTPUT": str(tmp_path / "output")}
    env.update(overrides)
    step = workflow()["jobs"]["quality"]["steps"][0]
    return subprocess.run(["bash", "-euo", "pipefail", "-c", step["run"]],
                          env=env, capture_output=True, text=True)


def test_workflow_is_reusable_only_and_read_only():
    """Prevent public central PRs from executing private consumer code."""
    data = workflow()
    assert data["on"] == {"workflow_call": ""}
    assert data["permissions"] == {"contents": "read"}
    job = data["jobs"]["quality"]
    assert "if" not in job
    assert job["runs-on"] == {"group": "CWL law CI", "labels": ["self-hosted", "Linux", "X64", "law-ai-agent-ci"]}
    assert job["strategy"]["max-parallel"] == "1"
    assert job["strategy"]["matrix"]["python-version"] == ["3.12", "3.14"]
    assert job["timeout-minutes"] == "20"
    steps = job["steps"]
    assert "uses" not in steps[0]
    checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 2
    assert {s["with"]["path"] for s in checkouts} == {"source", "central"}
    assert all(s["with"]["persist-credentials"] == "false" for s in checkouts)
    assert checkouts[1]["with"]["ref"] == "${{ job.workflow_sha }}"
    assert checkouts[1]["with"]["repository"] == "${{ job.workflow_repository }}"
    assert "secrets" not in WORKFLOW.read_text()


@pytest.mark.parametrize("event", ["push", "pull_request", "workflow_dispatch"])
def test_admission_accepts_only_owned_events(tmp_path, event):
    """Admit exact owned heads before either checkout."""
    assert admission(tmp_path, event=event).returncode == 0


@pytest.mark.parametrize("changes", [
    {"repository": "ContextualWisdomLab/.github"},
    {"event": "pull_request_target"},
    {"SOURCE_SHA": "a" * 39},
    {"SOURCE_SHA": "A" * 40},
    {"CALLER_REF": "refs/heads/develop"},
    {"CENTRAL_REPOSITORY": "attacker/.github"},
    {"CENTRAL_SHA": "a" * 39},
    {"CENTRAL_REF": "ContextualWisdomLab/.github/.github/workflows/law-ai-agent-ci.yml@main"},
    {"payload": {"after": "b" * 40}},
    {"payload": {"deleted": True}},
    {"event": "pull_request", "payload": {"pull_request": {"head": {"sha": SHA, "repo": {"full_name": "fork/law-ai-agent"}}, "base": {"ref": "main", "repo": {"full_name": "ContextualWisdomLab/law-ai-agent"}}}}},
])
def test_admission_rejects_untrusted_metadata(tmp_path, changes):
    """Forks, other repos, mutable refs, and malformed heads fail rather than skip."""
    assert admission(tmp_path, **changes).returncode != 0


def helper(*args, env=None):
    """Run the owned helper as a child process; fixture tools are synthetic only."""
    return subprocess.run(["bash", str(HELPER), *map(str, args)],
                          env=env, capture_output=True, text=True, cwd=ROOT.parent)


@pytest.mark.parametrize("skipped,expected", [(0, 0), (1, 1)])
def test_junit_requires_executed_tests_without_skips(tmp_path, skipped, expected):
    """A passing pytest exit cannot hide skipped database tests."""
    report = tmp_path / "junit.xml"
    report.write_text(f'<testsuites><testsuite tests="343" failures="0" errors="0" skipped="{skipped}"/></testsuites>')
    assert helper("verify-junit", report).returncode == expected


def test_empty_junit_is_not_execution_evidence(tmp_path):
    """Empty test collections fail closed."""
    report = tmp_path / "junit.xml"
    report.write_text('<testsuites><testsuite tests="0" skipped="0"/></testsuites>')
    assert helper("verify-junit", report).returncode != 0


@pytest.mark.parametrize("names,expected", [
    (["law.whl", "law.tar.gz"], 0),
    (["law.whl", "old.whl", "law.tar.gz"], 1),
    (["law.whl"], 1),
    (["law.whl", "law.tar.gz", "old.txt"], 1),
])
def test_dist_cardinality_rejects_previous_builds(tmp_path, names, expected):
    """Only one fresh wheel and one fresh source archive are accepted."""
    for name in names:
        (tmp_path / name).touch()
    assert helper("verify-dist", tmp_path).returncode == expected


def test_run_rejects_mismatched_checkout_before_creating_cluster(tmp_path):
    """Bad source identity must not start PostgreSQL or uv."""
    env = {**os.environ, "LAW_CI_SOURCE": str(ROOT), "LAW_CI_SOURCE_SHA": SHA,
           "LAW_CI_PYTHON_VERSION": "3.14", "RUNNER_TEMP": str(tmp_path)}
    result = helper("run", env=env)
    assert result.returncode != 0
    assert "source identity refused" in result.stderr
    assert not list(tmp_path.iterdir())


def embedded_migration_block(installed=False):
    """Extract the real heredoc, not a reimplementation of its acceptance logic."""
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY", HELPER.read_text(), re.S)
    marker = 'outside the source checkout' if installed else 'fresh, approved test-only database'
    return next(block for block in blocks if marker in block)


def migration_fixture(tmp_path, count=5):
    """Make archived SQL resources and independent product-semantics ledger rows."""
    source = tmp_path / 'source'
    package = source / 'src/law_ai_agent'
    resources = package / 'migrations'
    resources.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    for version in reversed(range(1, count + 1)):
        name = {1: '001_initial.sql', 2: '002_revision_membership.sql'}.get(
            version, f'{version:03}_step.sql')
        # CRLF and non-ASCII catch raw-byte hashing in place of read_text().encode().
        (resources / name).write_bytes(
            f'-- 단계 {version}\r\nSELECT {version};\r\n'.encode())
    rows = [{'version': int(path.name.split('_')[0]),
             'checksum': hashlib.sha256(path.read_text().encode()).hexdigest()}
            for path in sorted(resources.iterdir())]
    manifest = tmp_path / 'source-migrations.json'
    return source, resources, rows, manifest


def run_migration_block(source, rows, manifest, *, optimized=False):
    """Run production preflight with only its package/connection boundary synthetic."""
    package = source / 'src/law_ai_agent'
    trace = source / 'trace.json'
    (package / 'postgres.py').write_text(textwrap.dedent('''\
        import json
        from pathlib import Path
        class Connection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def commit(self):
                record('commit')
            def execute(self, query):
                record(query)
                rows = json.loads(Path('rows.json').read_text())
                if 'checksum' not in query:
                    return [{'version': row['version']} for row in rows]
                return rows
        def record(event):
            path = Path('trace.json')
            events = json.loads(path.read_text()) if path.exists() else []
            path.write_text(json.dumps(events + [event]))
        def connect(url, *, test_only):
            if test_only is not True:
                raise ValueError('test_only boundary lost')
            record('test_only')
            return Connection()
        class PostgresStore:
            def __init__(self, connection):
                self.connection = connection
            def migrate(self):
                record('migrate')
        '''))
    (source / 'rows.json').write_text(json.dumps(rows))
    wrapper = ('import sys; sys.path.insert(0, "src"); ' +
               f'exec(compile({embedded_migration_block()!r}, "<preflight>", "exec"))')
    env = {**os.environ, 'LAW_CI_PYTHON_VERSION': f'{sys.version_info.major}.{sys.version_info.minor}',
           'LAW_AGENT_TEST_DATABASE_URL': 'synthetic-only'}
    command = [sys.executable, *(['-O'] if optimized else []), '-I', '-c', wrapper, str(manifest)]
    result = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True)
    return result, trace


@pytest.mark.parametrize('count', [2, 5])
def test_preflight_accepts_complete_source_inventory(tmp_path, count):
    """Accept evolving inventories and retain sorted source names/checksums."""
    source, resources, rows, manifest = migration_fixture(tmp_path, count)
    result, trace = run_migration_block(source, rows, manifest)
    assert result.returncode == 0, result.stderr
    assert manifest.is_file(), 'source migration manifest was not retained'
    assert json.loads(manifest.read_text()) == [
        {'name': path.name, **row} for path, row in zip(sorted(resources.iterdir()), rows)]
    assert json.loads(trace.read_text())[:3] == ['test_only', 'migrate', 'commit']


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'checksum'])
@pytest.mark.parametrize('optimized', [False, True])
def test_preflight_rejects_nonexact_database_inventory(tmp_path, mutation, optimized):
    """Every database version and content digest must match, even under -O."""
    source, _, rows, manifest = migration_fixture(tmp_path, 2)
    if mutation == 'missing':
        rows.pop()
    elif mutation == 'extra':
        rows.append({'version': 3, 'checksum': 'a' * 64})
    else:
        rows[0]['checksum'] = 'a' * 64
    result, _ = run_migration_block(source, rows, manifest, optimized=optimized)
    assert result.returncode != 0, 'nonexact database inventory accepted'
    assert 'database migration inventory mismatch' in result.stderr


def run_installed_block(tmp_path, count=5, mutation=None, optimized=False):
    """Execute installed smoke with source manifest and separate installed resources."""
    source, resources, rows, manifest = migration_fixture(tmp_path, count)
    manifest.write_text(json.dumps([{'name': path.name, **row}
                                    for path, row in zip(sorted(resources.iterdir()), rows)]))
    site = tmp_path / 'installed' / 'lib' / 'site-packages'
    package = site / 'law_ai_agent'
    installed = package / 'migrations'
    installed.mkdir(parents=True)
    (package / '__init__.py').write_text('')
    for path in resources.iterdir():
        (installed / path.name).write_bytes(path.read_bytes())
    if mutation == 'missing':
        (installed / '001_initial.sql').unlink()
    elif mutation == 'extra':
        (installed / '999_extra.sql').write_text('SELECT 999;')
    elif mutation == 'checksum':
        (installed / '001_initial.sql').write_text('SELECT -1;')
    # -I excludes cwd, and this shim redirects imports only to an installed-like prefix.
    wrapper = ('import sys; sys.prefix = ' + repr(str(site.parent.parent)) +
               '; sys.path.insert(0, ' + repr(str(site)) + '); ' +
               f'exec(compile({embedded_migration_block(installed=True)!r}, "<installed>", "exec"))')
    return subprocess.run([sys.executable, *(['-O'] if optimized else []), '-I', '-c',
                           wrapper, str(manifest)], cwd=tmp_path, capture_output=True, text=True)


@pytest.mark.parametrize('count', [2, 5])
def test_installed_smoke_matches_retained_source_manifest(tmp_path, count):
    """Two and five independently installed resources match archived checksums."""
    result = run_installed_block(tmp_path, count)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'checksum'])
@pytest.mark.parametrize('optimized', [False, True])
def test_installed_smoke_rejects_divergence_from_source(tmp_path, mutation, optimized):
    """The installed resource set cannot self-attest or bypass checks under -O."""
    result = run_installed_block(tmp_path, mutation=mutation, optimized=optimized)
    assert result.returncode != 0, 'nonexact installed inventory accepted'
    assert 'installed migration inventory mismatch' in result.stderr


@pytest.mark.parametrize('optimized', [False, True])
def test_preflight_imports_product_only_after_valid_source_admission(tmp_path, optimized):
    """A valid source still imports the product and performs the test-only migration."""
    source, _, rows, manifest = migration_fixture(tmp_path, 5)
    imported = source / 'product-imported'
    (source / 'src/law_ai_agent/__init__.py').write_text(
        'from pathlib import Path\nPath("product-imported").write_text("imported")\n')
    result, trace = run_migration_block(source, rows, manifest, optimized=optimized)
    assert result.returncode == 0, result.stderr
    assert imported.read_text() == 'imported'
    assert manifest.is_file()
    assert json.loads(trace.read_text())[:3] == ['test_only', 'migrate', 'commit']


@pytest.mark.parametrize('component', ['src', 'src/law_ai_agent', 'src/law_ai_agent/migrations'])
@pytest.mark.parametrize('optimized', [False, True])
def test_preflight_rejects_linked_source_migration_ancestors(tmp_path, component, optimized):
    """An archived directory link cannot supply migration evidence from outside source."""
    source, _, rows, manifest = migration_fixture(tmp_path, 5)
    imported = source / 'product-imported'
    (source / 'src/law_ai_agent/__init__.py').write_text(
        'from pathlib import Path\nPath("product-imported").write_text("imported")\n')
    path = source / component
    outside = tmp_path / ('outside-' + path.name)
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=True)
    result, trace = run_migration_block(source, rows, manifest, optimized=optimized)
    assert result.returncode != 0, 'linked migration ancestor accepted'
    assert 'source migration inventory invalid' in result.stderr
    assert not manifest.exists()
    assert not imported.exists(), 'product imported before source admission'
    assert not trace.exists(), 'database access started before source admission'


@pytest.mark.parametrize('name', ['bad.sql', '001_a.txt', '000_zero.sql', '001_duplicate.sql'])
def test_preflight_rejects_invalid_source_migration_names(tmp_path, name):
    """Only uniquely numbered nonempty SQL migration resources are admissible."""
    source, resources, rows, manifest = migration_fixture(tmp_path, 2)
    (resources / name).write_text('SELECT 1;')
    result, _ = run_migration_block(source, rows, manifest)
    assert result.returncode != 0
    assert 'source migration inventory invalid' in result.stderr


def test_preflight_rejects_empty_source_migration(tmp_path):
    """An empty SQL file cannot be certified by a ledger row."""
    source, resources, rows, manifest = migration_fixture(tmp_path, 2)
    (resources / '001_initial.sql').write_text('  \n')
    result, _ = run_migration_block(source, rows, manifest)
    assert result.returncode != 0
    assert 'source migration inventory invalid' in result.stderr


def test_run_preserves_native_db_quality_and_artifact_contracts():
    """Bind the real execution path to locked isolated tooling and mandatory gates."""
    text = HELPER.read_text()
    for contract in (
        'pg_config --bindir', 'mktemp -d', 'chmod 700', 'listen_addresses=',
        'statement_timeout=10s', 'lock_timeout=2s', 'trap', 'LAW_AGENT_ROOT=',
        'LAW_AGENT_TEST_DATABASE_URL=', 'uv sync --locked', 'ruff check .',
        'ruff format --check .', 'mypy', 'pytest --cov', '--cov-fail-under=90',
        '--junitxml=', 'uv build --out-dir', '--no-create-gitignore', 'uv pip install --offline',
        '-I -', 'source-migrations.json', 'SELECT version, checksum',
        'test_only=True', 'git -C', 'archive', 'BASH_SOURCE',
    ):
        assert contract in text
    assert 'sudo' not in text and 'apt-get' not in text


def test_cleanup_absent_cluster_is_idempotent(tmp_path):
    """Admission failures leave no cluster, and always-cleanup remains safe."""
    assert helper('cleanup', env={**os.environ, 'RUNNER_TEMP': str(tmp_path)}).returncode == 0


def test_cleanup_preserves_cluster_when_pid_metadata_is_missing(tmp_path):
    """Missing PostgreSQL PID metadata is inconclusive, not a clean stop."""
    runner = tmp_path / 'runner'
    runner.mkdir(mode=0o700)
    root = runner / 'lawci.keep'
    cluster = root / 'data/private/postgres/cluster'
    cluster.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    marker = runner / 'law-ci-state-3.14'
    marker.write_text(str(root) + '\n')
    marker.chmod(0o600)
    tools = tmp_path / 'tools'
    tools.mkdir()
    pg = tools / 'pg_config'
    pg.write_text('#!/bin/bash\nprintf "%s\n" "$SYNTHETIC_TOOLS"\n')
    pg.chmod(0o700)
    env = {**os.environ, 'RUNNER_TEMP': str(runner),
           'SYNTHETIC_TOOLS': str(tools),
           'PATH': str(tools) + os.pathsep + os.environ['PATH']}
    result = helper('cleanup', env=env)
    assert result.returncode != 0
    assert 'PID metadata is missing; shutdown is inconclusive' in result.stderr
    assert cluster.is_dir()
    assert root.is_dir()
    assert marker.is_file()


@pytest.mark.parametrize('unsafe_child', [
    'data', 'private', 'postgres', 'cluster', 'postmaster-pid',
])
def test_cleanup_refuses_symlinked_cluster_boundaries(tmp_path, unsafe_child):
    """Never invoke PostgreSQL cleanup through a symlinked cluster boundary."""
    runner = tmp_path / 'runner'
    runner.mkdir(mode=0o700)
    root = runner / 'lawci.keep'
    root.mkdir(mode=0o700)
    cluster = root / 'data/private/postgres/cluster'
    foreign_root = tmp_path / 'foreign-root'
    foreign_cluster = foreign_root / 'data/private/postgres/cluster'
    foreign_cluster.mkdir(mode=0o700, parents=True)
    foreign_pid = foreign_cluster / 'postmaster.pid'
    foreign_pid.write_text('foreign\n')
    child_paths = {
        'data': Path('data'),
        'private': Path('data/private'),
        'postgres': Path('data/private/postgres'),
        'cluster': Path('data/private/postgres/cluster'),
    }
    if unsafe_child == 'postmaster-pid':
        cluster.mkdir(mode=0o700, parents=True)
        (cluster / 'postmaster.pid').symlink_to(foreign_pid)
    else:
        child_path = child_paths[unsafe_child]
        (root / child_path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        (root / child_path).symlink_to(foreign_root / child_path, target_is_directory=True)
    marker = runner / 'law-ci-state-3.14'
    marker.write_text(str(root) + '\n')
    marker.chmod(0o600)
    tools = tmp_path / 'tools'
    tools.mkdir()
    pg_config = tools / 'pg_config'
    pg_config.write_text('#!/bin/bash\nprintf "%s\\n" "$SYNTHETIC_TOOLS"\n')
    pg_config.chmod(0o700)
    pg_ctl = tools / 'pg_ctl'
    pg_ctl.write_text('#!/bin/bash\nprintf "called\\n" >> "$SYNTHETIC_TRACE"\nexit 9\n')
    pg_ctl.chmod(0o700)
    trace = tmp_path / 'trace'
    env = {**os.environ, 'RUNNER_TEMP': str(runner),
           'SYNTHETIC_TOOLS': str(tools), 'SYNTHETIC_TRACE': str(trace),
           'PATH': str(tools) + os.pathsep + os.environ['PATH']}
    result = helper('cleanup', env=env)
    assert result.returncode != 0
    assert not trace.exists()
    assert foreign_pid.read_text() == 'foreign\n'
    assert root.is_dir()
    assert marker.is_file()


def short_temp_root():
    """Select a canonical base leaving room for both private temporary roots."""
    base = Path(tempfile.gettempdir()).resolve()
    if len(str(base)) + len('/l.XXXXXXXX/lawci.XXXXXX') < 65:
        return base
    base = (Path.home() / '.cache/law-ci-tests').resolve()
    if len(str(base)) + len('/l.XXXXXXXX/lawci.XXXXXX') >= 65:
        raise ValueError('no short temporary root for law CI tests')
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = base.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
        raise ValueError('law CI test cache must be owned and private')
    return base


@pytest.mark.parametrize('layout', ['short', 'alias', 'long', 'default'])
def test_short_temp_root_is_canonical_and_socket_bounded(tmp_path, monkeypatch, layout):
    """Select usable defaults or home cache without forwarding temp aliases."""
    expected = short_temp_root()
    candidate = expected
    if layout == 'alias':
        candidate = tmp_path / 'alias'
        candidate.symlink_to(expected, target_is_directory=True)
    elif layout == 'long':
        candidate = tmp_path / ('temp-' + 'x' * 80)
        candidate.mkdir()
        expected = (Path.home() / '.cache/law-ci-tests').resolve()
    elif layout == 'default':
        monkeypatch.delenv('TMPDIR', raising=False)
        monkeypatch.setattr(tempfile, 'tempdir', None)
        candidate = Path(tempfile.gettempdir()).resolve()
        expected = candidate if len(str(candidate)) + len('/l.XXXXXXXX/lawci.XXXXXX') < 65 else (
            Path.home() / '.cache/law-ci-tests').resolve()
    if layout != 'default':
        monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(candidate))
    selected = short_temp_root()
    assert selected == expected
    assert selected == selected.resolve()
    assert all(not component.is_symlink() for component in (selected, *selected.parents))
    with tempfile.TemporaryDirectory(prefix='l.', dir=selected) as temp:
        assert len(str(Path(temp) / 'lawci.XXXXXX')) < 65
        assert Path(temp).stat().st_uid == os.getuid()
        assert Path(temp).stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize('stop_failure', [False, True])
def test_synthetic_child_failure_without_hermes_home(tmp_path, stop_failure):
    """Run the actual two cleanup cases with an empty HOME and long runner temp."""
    home = tmp_path / 'home'
    home.mkdir()
    runner = tmp_path / ('runner-' + 'x' * 80)
    runner.mkdir()
    assert not (home / '.hermes').exists()
    env = {**os.environ, 'HOME': str(home), 'TMPDIR': str(short_temp_root()),
           'RUNNER_TEMP': str(runner), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
    node = f'{__file__}::test_synthetic_child_failure_and_cleanup_are_not_success[{stop_failure}]'
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q',
                             '--basetemp', str(tmp_path / 'child'), node],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 passed' in result.stdout
    assert not (home / '.hermes').exists()
    assert not list(runner.iterdir())


@pytest.mark.parametrize('stop_failure', [False, True])
def test_synthetic_child_failure_and_cleanup_are_not_success(tmp_path, stop_failure):
    """Synthetic tools prove exit propagation and cleanup; not real DB evidence."""
    tools = tmp_path / 'tools'
    tools.mkdir()
    scripts = {
        'git': '#!/bin/bash\nif [[ "$*" == *rev-parse* ]]; then printf "%s\\n" "$LAW_CI_SOURCE_SHA"; else tar -cf - --files-from /dev/null; fi\n',
        'uv': '#!/bin/bash\nif [[ "$1" == --version ]]; then printf "uv 0.12.5 synthetic-only\\n"; else exit 37; fi\n',
        'pg_config': '#!/bin/bash\nprintf "%s\\n" "$SYNTHETIC_TOOLS"\n',
        'initdb': '#!/bin/bash\nmkdir -p "$2"\n',
        'pg_ctl': '#!/bin/bash\nif [[ "$*" == *start* ]]; then touch "$2/postmaster.pid"; else printf "stop\\n" >> "$SYNTHETIC_TRACE"; if [[ "$SYNTHETIC_STOP_EXIT" == 0 ]]; then rm -f "$2/postmaster.pid"; fi; exit "$SYNTHETIC_STOP_EXIT"; fi\n',
        'createdb': '#!/bin/bash\nexit 0\n',
        'psql': '#!/bin/bash\nexit 0\n',
    }
    for name, content in scripts.items():
        path = tools / name
        path.write_text(content)
        path.chmod(0o700)
    # Deep pytest roots exceed socket limits; choose a portable canonical base.
    with tempfile.TemporaryDirectory(prefix='l.', dir=short_temp_root()) as temp:
        sentinel = Path(temp) / 'keep'
        sentinel.write_text('unrelated')
        assert len(str(Path(temp) / 'lawci.XXXXXX')) < 65
        env = {**os.environ, 'PATH': str(tools) + os.pathsep + os.environ['PATH'],
               'LAW_CI_SOURCE': str(ROOT), 'LAW_CI_SOURCE_SHA': SHA,
               'LAW_CI_PYTHON_VERSION': '3.14', 'RUNNER_TEMP': temp,
               'SYNTHETIC_TOOLS': str(tools), 'SYNTHETIC_TRACE': str(tmp_path / 'trace'),
               'SYNTHETIC_STOP_EXIT': '9' if stop_failure else '0'}
        result = helper('run', env=env)
        assert result.returncode == 37
        assert (tmp_path / 'trace').read_text() == 'stop\n'
        assert bool(list(Path(temp).glob('lawci.*'))) == stop_failure
        if stop_failure:
            env['SYNTHETIC_STOP_EXIT'] = '0'
            assert helper('cleanup', env=env).returncode == 0
        assert sentinel.read_text() == 'unrelated'
        assert list(Path(temp).iterdir()) == [sentinel]


@pytest.mark.parametrize('unsafe', ['nested', 'public', 'symlink', 'parent-symlink', 'public-marker'])
def test_cleanup_refuses_unowned_or_non_immediate_roots(tmp_path, unsafe):
    """Hostile marker paths never grant recursive deletion authority."""
    runner = tmp_path / 'runner'
    runner.mkdir(mode=0o700)
    root = runner / 'lawci.keep'
    root.mkdir(mode=0o700)
    target = root
    if unsafe == 'nested':
        target = root / 'lawci.child'
        target.mkdir(mode=0o700)
    elif unsafe == 'public':
        root.chmod(0o755)
    elif unsafe == 'symlink':
        target = runner / 'lawci.link'
        target.symlink_to(root, target_is_directory=True)
    elif unsafe == 'parent-symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(runner, target_is_directory=True)
        runner = alias
        target = alias / root.name
    marker = runner / 'law-ci-state-3.14'
    marker.write_text(str(target) + '\n')
    marker.chmod(0o644 if unsafe == 'public-marker' else 0o600)
    tools = tmp_path / 'tools'
    tools.mkdir()
    pg = tools / 'pg_config'
    pg.write_text('#!/bin/bash\nprintf "%s\\n" "$SYNTHETIC_TOOLS"\n')
    pg.chmod(0o700)
    env = {**os.environ, 'RUNNER_TEMP': str(runner), 'SYNTHETIC_TOOLS': str(tools),
           'PATH': str(tools) + os.pathsep + os.environ['PATH']}
    assert helper('cleanup', env=env).returncode != 0
    assert root.is_dir()
    assert marker.is_file()


def test_run_installs_trap_before_state_and_verifies_actual_python_prefix():
    """State collisions preserve old markers and leave no newly owned root."""
    text = HELPER.read_text()
    assert text.index('trap on_exit EXIT') < text.index('test ! -e "$state"')
    assert 'state_owned=0' in text
    assert 'sys.version_info[:2]' in text
    assert 'Path(sys.prefix).resolve()' in text
