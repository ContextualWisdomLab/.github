#!/usr/bin/env python3
"""Run Noema LLM review and submit a non-OpenCode PR review verdict."""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _name in ("_noema_review_gate_a.py", "_noema_review_gate_b.py"):
    _path = _HERE / _name
    exec(compile(_path.read_text(encoding="utf-8"), str(_path), "exec"), globals())
