"""Smoke tests for repository fuzz targets."""

from __future__ import annotations

from fuzz.fuzz_opencode_review_normalize_output import TestOneInput


def test_opencode_review_normalizer_fuzz_target_handles_seed_inputs() -> None:
    """Exercise representative seed inputs without requiring Atheris locally."""
    seeds = [
        b"",
        b"plain text before {not json",
        b'{"head_sha":"other","result":"APPROVE"}',
        (
            b'prefix {"head_sha":"fuzz-head","run_id":"fuzz-run",'
            b'"run_attempt":"1","result":"REQUEST_CHANGES",'
            b'"reason":"missing evidence","summary":"coverage missing",'
            b'"findings":[]} suffix'
        ),
        b'{"nested":[{"path":"scripts/ci/opencode_review_normalize_output.py"}]}',
    ]
    for seed in seeds:
        TestOneInput(seed)
