"""Require self-hosted CI without admitting PR code to privileged runner pools.

The isolated label is an operator provisioning requirement, not evidence that an
isolated machine exists. Existing trusted control and review selectors retain
their main-ref predicates; their non-main fallback must never be GitHub-hosted.
"""
from pathlib import Path
import re


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
    """Keep executable PR and reusable matrix jobs off privileged host pools."""
    for path in sorted(Path('.github/workflows').glob('*.yml')):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if not re.match(r'^    runs-on:', line):
                continue
            if line.strip() == 'runs-on:':
                group = lines[index + 1]
                assert any(name in group for name in (
                    'CWL central control', 'CWL central CodeQL', 'CWL central OpenCode'
                )), (path, group)
            else:
                assert 'cwlab-ci-isolated' in line, (path, line)


def test_isolated_fallback_never_selects_privileged_group() -> None:
    """Any expression's fallback remains independent of privileged groups."""
    for path in sorted(Path('.github/workflows').glob('*.yml')):
        for line in path.read_text().splitlines():
            if re.match(r'^    runs-on:', line) and '||' in line and 'matrix.config.os' not in line:
                fallback = line.rsplit('||', 1)[1]
                assert 'cwlab-ci-isolated' in fallback, (path, fallback)
                assert 'CWL central' not in fallback and 'CWL MCP' not in fallback
