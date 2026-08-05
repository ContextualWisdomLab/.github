#!/usr/bin/env python3
"""Make the Git ownership contract hermetic to runner-global configuration."""

from pathlib import Path

path = Path("tests/test_opencode_agent_contract.py")
text = path.read_text(encoding="utf-8")
old = '''    base_env = {
        **os.environ,
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
    }
'''
new = '''    base_env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
    }
'''
if text.count(old) != 1:
    raise SystemExit(
        f"expected one runner-global Git isolation anchor, found {text.count(old)}"
    )
path.write_text(text.replace(old, new, 1), encoding="utf-8")
