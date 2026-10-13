"""Require self-hosted CI without admitting PR code to privileged runner pools.

The isolated label is an operator provisioning requirement, not evidence that an
isolated machine exists. Existing trusted control and review selectors retain
their main-ref predicates; their non-main fallback must never be GitHub-hosted.
"""
from pathlib import Path
import json
import re
import pytest
import yaml


STATIC_RUNNER_GROUP_LABELS = {
    'CWL central control': set(),
    'CWL central CodeQL': set(),
    'CWL central OpenCode': set(),
    'CWL CI isolated': {'cwlab-ci-isolated'},
    'CWL law CI': {'law-ai-agent-ci'},
}


def required_static_labels(group: object) -> set[str]:
    """Return the exact additional labels admitted for a static runner group."""
    assert group in STATIC_RUNNER_GROUP_LABELS, ('unsupported static group', group)
    return {'self-hosted', 'linux', 'x64'} | STATIC_RUNNER_GROUP_LABELS[group]


def test_every_runner_requires_self_hosted_and_no_hosted_fallback() -> None:
    """Inspect every declaration, including expression and matrix selectors."""
    declarations = []
    for path in sorted(Path('.github/workflows').glob('*.yml')):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if re.match(r'^    runs-on:', line):
                block = line
                if line.strip() == 'runs-on:':
                    block += '\n' + '\n'.join(lines[index + 1:index + 3])
                declarations.append((path, block))
    assert declarations
    for path, block in declarations:
        assert 'self-hosted' in block, (path, block)
        assert not re.search(r'fromJSON\(\'\["ubuntu-|\|\| \'"ubuntu-', block), (path, block)
        assert not re.search(r'runs-on: (?:ubuntu-|windows-|macos-)', block), (path, block)


def test_nonprivileged_runners_require_isolated_label() -> None:
    """Check actual YAML selectors, including static labels and both extensions."""
    paths = sorted(set(Path('.github/workflows').glob('*.yml')) |
                   set(Path('.github/workflows').glob('*.yaml')))
    observed = 0
    groups = set(STATIC_RUNNER_GROUP_LABELS)
    for path in paths:
        for job_id, job in yaml.safe_load(path.read_text())['jobs'].items():
            if 'runs-on' not in job:
                continue
            observed += 1
            runner = job['runs-on']
            if isinstance(runner, dict):
                group = runner.get('group')
                if isinstance(group, str) and group.startswith('${{'):
                    # Dynamic predicates remain covered by the exact fallback,
                    # typed-pair and R-matrix contracts, not literal evaluation.
                    assert any(name in group for name in groups), (path, job_id, group)
                    continue
                labels = runner.get('labels')
                assert isinstance(labels, list) and all(isinstance(label, str) for label in labels), (
                    path, job_id, 'static labels must be a string list', labels,
                )
                required = required_static_labels(group)
                assert required.issubset(label.lower() for label in labels), (
                    path, job_id, 'missing required static labels', required.difference(labels),
                )
            else:
                assert isinstance(runner, str) and 'cwlab-ci-isolated' in runner, (path, job_id, runner)
    assert observed, 'runner selector coverage is empty'


def test_static_runner_group_policy_is_explicit_and_fail_closed() -> None:
    """Bind dedicated groups to their isolation labels and reject unknown groups."""
    assert required_static_labels('CWL law CI') == {
        'self-hosted', 'linux', 'x64', 'law-ai-agent-ci',
    }
    with pytest.raises(AssertionError, match='unsupported static group'):
        required_static_labels('CWL ungoverned CI')


def test_isolated_fallback_never_selects_privileged_group() -> None:
    """Inspect scalar and typed runner fallbacks, never an empty declaration set."""
    observed = 0
    expected = {
        'group': 'CWL CI isolated',
        'labels': ['self-hosted', 'linux', 'x64', 'cwlab-ci-isolated'],
    }
    paths = sorted(set(Path('.github/workflows').glob('*.yml')) |
                   set(Path('.github/workflows').glob('*.yaml')))
    for path in paths:
        for job_id, job in yaml.safe_load(path.read_text())['jobs'].items():
            runner = job.get('runs-on')
            fields = list(runner.values()) if isinstance(runner, dict) else [runner]
            expressions = [field for field in fields if isinstance(field, str) and
                           field.startswith('${{') and '||' in field and
                           'matrix.config.os' not in field]
            if not expressions:
                continue
            observed += 1
            for expression in expressions:
                fallback = expression.rsplit('||', 1)[1]
                match = re.fullmatch(
                    r"\s*(?:fromJSON\(\s*)?'(\{[^']*\})'\s*\)*\s*"
                    r"(?:\.group|\.labels)?\s*\}\}", fallback,
                )
                assert match is not None, (path, job_id, 'unsupported fallback', fallback)
                assert json.loads(match.group(1)) == expected, (
                    path, job_id, 'unsafe fallback', fallback,
                )
    assert observed == 29, ('conditional runner fallback coverage', observed)


def test_isolated_label_is_scoped_to_dedicated_runner_group() -> None:
    """A mutable label cannot replace the isolated runner access boundary."""
    for path in sorted(Path('.github/workflows').glob('*.yml')):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if not re.match(r'^    runs-on:', line):
                continue
            block = line
            if line.strip() == 'runs-on:':
                block += '\n' + '\n'.join(lines[index + 1:index + 3])
            if 'cwlab-ci-isolated' in block:
                assert 'CWL CI isolated' in block, (path, block)


TRUSTED_MAIN_UNION_SELECTORS = {
    '.github/workflows/actions-queue-health.yml': {'collect'},
    '.github/workflows/audit-central-ruleset.yml': {'audit'},
    '.github/workflows/organization-commercial-readiness-loop.yml': {'coordinate'},
    '.github/workflows/pr-auto-rebase.yml': {'auto-rebase'},
    '.github/workflows/repository-metadata-reconcile.yml': {'validate', 'apply'},
    '.github/workflows/sbom-inventory-scheduler.yml': {'aggregate-sbom-inventory'},
}


def test_trusted_main_union_selectors_preserve_control_and_isolated_fallback() -> None:
    """Resolve main/head routing conflicts without restoring hosted fallback."""
    trusted_main = '{"group":"CWL MCP remediation","labels":["self-hosted","linux","x64"]}'
    isolated_fallback = (
        '{"group":"CWL CI isolated",'
        '"labels":["self-hosted","linux","x64","cwlab-ci-isolated"]}'
    )
    for workflow_path, job_ids in TRUSTED_MAIN_UNION_SELECTORS.items():
        workflow = yaml.safe_load(Path(workflow_path).read_text())
        for job_id in job_ids:
            mapping = workflow['jobs'][job_id]['runs-on']
            assert isinstance(mapping, dict), (workflow_path, job_id, mapping)
            assert set(mapping) == {'group', 'labels'}
            group = mapping['group']
            labels = mapping['labels']
            assert group.endswith(').group }}')
            assert labels.endswith(').labels }}')
            assert group.removesuffix(').group }}') == labels.removesuffix(').labels }}')
            runner = '${{ ' + group[5:].removesuffix(').group }}') + ' }}'
            expected = (
                "${{ github.repository == 'ContextualWisdomLab/.github' && "
                "github.ref == 'refs/heads/main' && "
                "endsWith(github.workflow_ref, '@refs/heads/main') && "
                f"fromJSON('{trusted_main}') || fromJSON('{isolated_fallback}') }}" + "}"
            )
            assert runner == expected, (workflow_path, job_id, runner)
            condition = runner[4:].split(' && fromJSON(', 1)[0]
            for repository in ('ContextualWisdomLab/.github', 'ContextualWisdomLab/example'):
                for ref in ('refs/heads/main', 'refs/pull/2565/merge', 'refs/heads/candidate'):
                    for workflow_ref in ('main', 'candidate'):
                        terms = {
                            "github.repository == 'ContextualWisdomLab/.github'": repository == 'ContextualWisdomLab/.github',
                            "github.ref == 'refs/heads/main'": ref == 'refs/heads/main',
                            "endsWith(github.workflow_ref, '@refs/heads/main')": workflow_ref == 'main',
                        }
                        admitted = all(terms[term] for term in condition.split(' && '))
                        wanted = repository == 'ContextualWisdomLab/.github' and ref == 'refs/heads/main' and workflow_ref == 'main'
                        assert admitted == wanted, (workflow_path, job_id, repository, ref, workflow_ref)
            assert 'ubuntu-24.04' not in runner
            assert 'ubuntu-latest' not in runner
