"""Atheris fuzz harness for OpenCode review-output normalization."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import atheris


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
NORMALIZER_PATH = REPO_ROOT / "scripts" / "ci" / "opencode_review_normalize_output.py"


def _load_normalizer():
    """Load the normalizer module without requiring package installation."""
    spec = importlib.util.spec_from_file_location(
        "opencode_review_normalize_output", NORMALIZER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load OpenCode normalizer module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NORMALIZER = _load_normalizer()


def TestOneInput(data: bytes) -> None:
    """Feed arbitrary model text into the JSON extraction path."""
    try:
        text = data.decode("utf-8", errors="ignore")
        NORMALIZER.extract_json_object(text)
    except (ValueError, UnicodeError):
        return


def main() -> None:
    """Run the Atheris entry point."""
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
