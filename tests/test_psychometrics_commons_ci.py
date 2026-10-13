"""Preserve Runtime CI gates behind fixed-caller isolated-runner admission."""

from pathlib import Path
import os
import subprocess

import pytest
import yaml

WORKFLOW = Path('.github/workflows/psychometrics-commons-ci.yml')
CONSUMER = 'ContextualWisdomLab/psychometrics-commons'
IMAGE = 'postgres:18-alpine@sha256:9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15'


def workflow():
    """Parse YAML without converting the GitHub on key into a boolean."""
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def test_only_fixed_same_repo_open_prs_obtain_runners():
    """All three jobs must exclude forks and non-PR callers before allocation."""
    data = workflow()
    assert data['on'] == {'workflow_call': ''}
    assert data['permissions'] == {'contents': 'read'}
    assert set(data['jobs']) == {'rust-quality', 'line-coverage', 'branch-coverage'}
    for job in data['jobs'].values():
        guard = job['if']
        for predicate in (
            f"github.repository == '{CONSUMER}'", "github.event_name == 'pull_request'",
            "github.event.action != 'closed'", "github.event.pull_request.state == 'open'",
            'github.event.pull_request.number > 0', 'github.event.pull_request.draft == false',
            'github.event.pull_request.head.repo.full_name == github.repository',
            'github.event.pull_request.base.repo.full_name == github.repository',
            "github.event.pull_request.base.ref == 'main'",
            "startsWith(github.ref, 'refs/pull/')", "endsWith(github.ref, '/merge')",
        ):
            assert predicate in guard
        assert job['runs-on'] == {
            'group': 'CWL CI isolated',
            'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated'],
        }
        steps = job['steps']
        assert steps[0]['name'] == 'Validate fixed caller and exact head before checkout'
        assert steps[1]['with'] == {
            'ref': '${{ github.event.pull_request.head.sha }}', 'persist-credentials': 'false',
        }
        assert steps[2]['run'] == 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD_SHA"'
    assert 'secrets.' not in WORKFLOW.read_text()
    assert 'github.sha' not in WORKFLOW.read_text()
    assert 'concurrency:' not in WORKFLOW.read_text()


def test_ephemeral_postgres_uses_random_port_and_exact_image():
    """Concurrent jobs must not bind a shared host database or fixed TCP port."""
    for job in workflow()['jobs'].values():
        service = job['services']['postgres']
        assert service['image'] == IMAGE
        assert service['ports'] == ['5432']
        assert service['env']['POSTGRES_PASSWORD'] == 'ci_${{ github.run_id }}_${{ github.run_attempt }}'
        assert service['env']['POSTGRES_DB'] == 'psychometrics_commons_test'
        connection = next(s for s in job['steps'] if s['name'] == 'Configure ephemeral PostgreSQL test connection')
        assert "job.services.postgres.ports['5432']" in connection['run']
        assert 'host=localhost port=%s' in connection['run']
        assert 'rm -rf' not in WORKFLOW.read_text()


def test_original_names_and_all_quality_commands_are_preserved():
    """Pinned binaries and existing lint/test/doc/lock gates are never optional."""
    data = workflow()
    assert [j['name'] for j in data['jobs'].values()] == [
        'Format, lint, test, and rustdoc', 'Production line coverage', 'Production branch coverage',
    ]
    assert data['env']['RUSTFLAGS'] == '-Dwarnings'
    assert data['env']['RUSTDOCFLAGS'] == '-Dwarnings'
    assert data['env']['CARGO_LLVM_COV_VERSION'] == '0.8.6'
    steps = data['jobs']['rust-quality']['steps']
    commands = {s.get('run') for s in steps}
    for command in (
        'rustup toolchain install 1.97.1 --profile minimal --component clippy --component rustfmt',
        'cargo +1.97.1 fmt --all -- --check', 'cargo +1.97.1 check --locked --all-targets',
        'git diff --exit-code -- Cargo.lock', 'cargo +1.97.1 clippy --all-targets -- -D warnings',
        'cargo +1.97.1 test --all-targets', "python3 -m unittest discover -s tests -p 'test_*.py' -v",
        'cargo +1.97.1 doc --no-deps',
    ):
        assert command in commands
    assert 'continue-on-error' not in WORKFLOW.read_text()


def test_complete_coverage_commands_and_threshold_contract_are_unchanged():
    """Production check_coverage.py remains the complete-coverage authority."""
    for name, toolchain, report, kind in (
        ('line-coverage', '1.97.1', 'coverage.json', 'lines'),
        ('branch-coverage', 'nightly-2026-08-18', 'coverage-branches.json', 'branches'),
    ):
        commands = {s.get('run') for s in workflow()['jobs'][name]['steps']}
        assert f'rustup toolchain install {toolchain} --profile minimal --component llvm-tools-preview' in commands
        assert f'cargo +{toolchain} install cargo-llvm-cov --locked --version "$CARGO_LLVM_COV_VERSION"' in commands
        assert f'cargo +{toolchain} llvm-cov --version | grep -F "$CARGO_LLVM_COV_VERSION"' in commands
        branch = '--branch ' if kind == 'branches' else ''
        assert f'cargo +{toolchain} llvm-cov {branch}--json --summary-only --output-path {report}' in commands
        assert f'python3 scripts/check_coverage.py {report} --kind {kind}' in commands


@pytest.mark.parametrize('updates', [
    {}, {'TARGET_REPOSITORY': 'outsider/repo'}, {'SOURCE_REPOSITORY': 'outsider/fork'},
    {'BASE_REPOSITORY': 'outsider/base'}, {'BASE_REF': 'feature'}, {'GITHUB_EVENT_NAME': 'push'},
    {'HEAD_SHA': ''}, {'HEAD_SHA': 'A' * 40}, {'PR_NUMBER': '0'}, {'PR_STATE': 'closed'},
    {'PR_DRAFT': 'true'}, {'GITHUB_REF': 'refs/pull/2/merge'},
])
def test_actual_precheckout_shell_rejects_untrusted_identity(updates):
    """Execute every defensive admission block using only synthetic event metadata."""
    env = {**os.environ, 'TARGET_REPOSITORY': CONSUMER, 'SOURCE_REPOSITORY': CONSUMER,
           'BASE_REPOSITORY': CONSUMER, 'BASE_REF': 'main', 'GITHUB_EVENT_NAME': 'pull_request',
           'HEAD_SHA': 'a' * 40, 'PR_NUMBER': '1', 'PR_STATE': 'open', 'PR_DRAFT': 'false',
           'GITHUB_REF': 'refs/pull/1/merge', **updates}
    for job in workflow()['jobs'].values():
        result = subprocess.run(['bash', '-euo', 'pipefail', '-c', job['steps'][0]['run']],
                                env=env, capture_output=True, text=True, check=False)
        assert result.returncode == (0 if not updates else 1), result.stderr
