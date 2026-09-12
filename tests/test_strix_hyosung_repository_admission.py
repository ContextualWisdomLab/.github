"""The two Strix repository checks admit only the scoped Hyosung consumer."""

import os
from pathlib import Path
import re
import subprocess

import pytest


@pytest.mark.parametrize('variable', ['TARGET_REPOSITORY', 'REPOSITORY'])
def test_strix_repository_boundary(variable):
    """Execute each workflow regex against legitimate and out-of-scope names."""
    workflow = Path('.github/workflows/strix.yml').read_text()
    patterns = [pattern for pattern in re.findall(r'"\$' + variable + r'" =~ (\^[^ ]+)', workflow)
                if 'ContextualWisdomLab' in pattern]
    assert len(patterns) == 1
    for repository, accepted in (
        ('ContextualWisdomLab/.github', True),
        ('HYOSUNG-ITX-AI-Business-Department/llm-gateway-console', True),
        ('HYOSUNG-ITX-AI-Business-Department/another-service', False),
        ('other/llm-gateway-console', False),
        ('HYOSUNG-ITX-AI-Business-Department/llm-gateway-console-extra', False),
        ('HYOSUNG-ITX-AI-Business-Department/llm-gateway-console\n', False),
    ):
        result = subprocess.run(
            ['bash', '-c', '[[ "$REPOSITORY" =~ ' + patterns[0] + ' ]]'],
            env=dict(os.environ, REPOSITORY=repository), capture_output=True,
            text=True, timeout=5,
        )
        assert (result.returncode == 0) == accepted, repository
