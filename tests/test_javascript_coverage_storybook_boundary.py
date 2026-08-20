"""Regression tests for Storybook development evidence classification."""

from __future__ import annotations

import pytest

from scripts.ci import javascript_coverage_gate as gate


@pytest.mark.parametrize(
    "path",
    [
        ".storybook/main.ts",
        ".storybook/preview.ts",
        "packages/editor/.storybook/main.ts",
        "stories/Foo.stories.tsx",
        "src/components/Foo.stories.ts",
    ],
)
def test_storybook_development_evidence_is_not_product_runtime(path: str) -> None:
    assert not gate.is_runtime_source(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/foo.ts",
        "stories/runtime.ts",
        "src/Foo.story.tsx",
        "src/Foo.stories-helper.ts",
        "src/storybook/main.ts",
    ],
)
def test_nearby_and_near_miss_product_modules_remain_governed(path: str) -> None:
    assert gate.is_runtime_source(path)
