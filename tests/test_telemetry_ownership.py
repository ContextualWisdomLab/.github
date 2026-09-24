"""Canary checks for the shared telemetry ownership boundary."""

import sys
from pathlib import Path

import pytest

from scripts.ci import check_telemetry_ownership as ownership

scan_source = ownership.scan_source
scan_tree = ownership.scan_tree


def test_scan_source_finds_aliased_and_qualified_bootstrap_only() -> None:
    """Calls are findings; prose and unused imports are not."""
    source = '''
from opentelemetry.sdk.trace import TracerProvider as Provider
from opentelemetry.exporter.otlp.proto.http import trace_exporter as otlp
from opentelemetry.sdk.metrics import MeterProvider
Provider()
otlp.OTLPSpanExporter()
message = "OTLPSpanExporter()"
'''
    assert scan_source(source) == ((5, "Provider"), (6, "OTLPSpanExporter"))


def test_scan_tree_skips_tests_and_reports_product_call(tmp_path) -> None:
    """The canary scans product source without treating test fixtures as owners."""
    package = tmp_path / "product"
    package.mkdir()
    (package / "telemetry.py").write_text(
        "from opentelemetry.sdk.trace import TracerProvider\nTracerProvider()\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_telemetry.py").write_text(
        "from opentelemetry.sdk.trace import TracerProvider\nTracerProvider()\n",
        encoding="utf-8",
    )
    assert scan_tree(tmp_path) == ("product/telemetry.py:2: product-owned TracerProvider()",)


def test_qualified_import_and_non_otel_lookalike() -> None:
    """Only an OpenTelemetry import can authorize a qualified finding."""
    source = '''
import opentelemetry.sdk.trace as sdk
import opentelemetry.sdk.trace
import unrelated
sdk.TracerProvider()
opentelemetry.sdk.trace.TracerProvider()
unrelated.TracerProvider()
sdk.get_tracer()
'''
    assert scan_source(source) == ((5, "TracerProvider"), (6, "TracerProvider"))


def test_root_opentelemetry_imports_cannot_hide_provider_construction() -> None:
    source = '''
import opentelemetry
from opentelemetry import sdk as otel_sdk
opentelemetry.sdk.trace.TracerProvider()
otel_sdk.metrics.MeterProvider()
'''
    assert scan_source(source) == ((4, "TracerProvider"), (5, "MeterProvider"))


def test_scan_tree_skips_symlink_and_empty_tree(tmp_path) -> None:
    """A symlink cannot expand the canary beyond the checkout."""
    outside = tmp_path.parent / "outside_telemetry.py"
    outside.write_text(
        "from opentelemetry.sdk.trace import TracerProvider\nTracerProvider()\n",
        encoding="utf-8",
    )
    (tmp_path / "link.py").symlink_to(outside)
    assert scan_tree(tmp_path) == ()


def test_main_reports_positive_and_empty_canary(tmp_path, monkeypatch, capsys) -> None:
    """The CLI's exit status matches its printed report."""
    monkeypatch.setattr(sys, "argv", ["check", str(tmp_path)])
    assert ownership.main() == 0
    assert "No product-owned" in capsys.readouterr().out

    (tmp_path / "telemetry.py").write_text(
        "from opentelemetry.sdk.trace import TracerProvider\nTracerProvider()\n",
        encoding="utf-8",
    )
    assert ownership.main() == 1
    assert "telemetry.py:2" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["check", str(tmp_path / "missing")])
    with pytest.raises(SystemExit, match="2"):
        ownership.main()


def test_reusable_gate_reads_exact_pr_head_with_pinned_read_only_scanner() -> None:
    workflow = Path(".github/workflows/telemetry-ownership.yml").read_text(encoding="utf-8")
    assert "workflow_call:" in workflow and "pull_request_target:" not in workflow
    assert "contents: read" in workflow and "persist-credentials: false" in workflow
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "repository: ContextualWisdomLab/.github" in workflow
    assert "ref: 8821c67f28d89b805f0d6b059fa1330c21227bd8" in workflow
    assert "python3 governance/scripts/ci/check_telemetry_ownership.py product" in workflow
