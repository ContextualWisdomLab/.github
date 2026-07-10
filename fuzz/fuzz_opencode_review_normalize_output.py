#!/usr/bin/env python3
"""Atheris target for OpenCode review-output normalization."""

from __future__ import annotations

import sys

from scripts.ci import opencode_review_normalize_output as normalizer

MAX_INPUT_BYTES = 64 * 1024
MAX_OBJECTS_TO_VALIDATE = 16


def TestOneInput(data: bytes) -> None:
    """Fuzz JSON extraction and control-block validation from model output."""
    text = data[:MAX_INPUT_BYTES].decode("utf-8", errors="replace")
    values = normalizer.iter_json_objects(text)
    for value in values[:MAX_OBJECTS_TO_VALIDATE]:
        if isinstance(value, dict):
            normalizer.valid_control(
                value,
                expected_head_sha="fuzz-head",
                expected_run_id="fuzz-run",
                expected_run_attempt="1",
            )


def main() -> None:
    """Run the Atheris fuzz loop."""
    import atheris

    atheris.Setup(sys.argv, [TestOneInput])
    atheris.Fuzz()


if __name__ == "__main__":
    main()
