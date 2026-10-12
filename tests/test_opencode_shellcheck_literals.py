"""Bind each lint quote repair to the original literal bytes and actual Bash."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"
OPERANDS = json.loads((ROOT / "tests/fixtures/opencode_shell_literal_operands.json").read_text())


@pytest.mark.parametrize("row", OPERANDS, ids=lambda row: row["literal_sha256"][:12])
def test_migrated_operand_preserves_original_literal(row):
    """Inspect each shipped replacement, then expand it without its consumer."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count(row["after"]) == row["count"]
    assert hashlib.sha256(row["expected"].encode()).hexdigest() == row["literal_sha256"]
    # No bash/jq/GraphQL consumer runs here; only operand expansion into printf.
    start = text.index(row["after"])
    actual = text[start:start + len(row["after"])]
    result = subprocess.run(
        ["bash", "-eu", "-c", "printf '%s' " + actual],
        env={"PATH": os.defpath, "LC_ALL": "C", "n": "SENTINEL", "owner": "SENTINEL"},
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    assert result.stdout == row["expected"].encode()
