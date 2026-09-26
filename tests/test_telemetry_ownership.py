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


def test_shadowed_names_and_local_imports_do_not_cross_scopes() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
import opentelemetry.sdk.metrics as metrics
def parameter(TracerProvider):
    return TracerProvider()
def reassigned():
    TracerProvider = lambda: None
    metrics = object()
    TracerProvider()
    metrics.MeterProvider()
def direct():
    return TracerProvider()
def local():
    from opentelemetry.sdk.metrics import MeterProvider
    return MeterProvider()
def sibling():
    return MeterProvider()
'''
    assert scan_source(source) == ((12, "TracerProvider"), (15, "MeterProvider"))


def test_nested_import_cannot_shadow_outer_function_binding() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
def outer():
    def inner():
        from elsewhere import TracerProvider
        return TracerProvider()
    return TracerProvider()
'''
    assert scan_source(source) == ((7, "TracerProvider"),)


def test_default_and_assignment_rhs_are_scanned_before_binding() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
def start(provider=TracerProvider()):
    return provider
TracerProvider = TracerProvider()
'''
    assert scan_source(source) == ((3, "TracerProvider"), (5, "TracerProvider"))


def test_factory_aliases_are_tracked_until_shadowed() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider as Provider
import opentelemetry.sdk.metrics as metrics
trace_factory = Provider
metric_factory: object = metrics.MeterProvider
trace_factory()
metric_factory()
trace_factory = lambda: None
trace_factory()
if enabled:
    selected = Provider
else:
    selected = lambda: None
selected()
'''
    assert scan_source(source) == ((6, "trace_factory"), (7, "metric_factory"), (14, "selected"))


def test_method_does_not_inherit_class_import() -> None:
    source = '''
class Owner:
    from opentelemetry.sdk.trace import TracerProvider
    def create(self):
        return TracerProvider()
    created = TracerProvider()
'''
    assert scan_source(source) == ((6, "TracerProvider"),)


def test_comprehension_target_does_not_shadow_outer_import() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
def build(providers):
    [TracerProvider for TracerProvider in providers]
    [TracerProvider() for TracerProvider in providers]
    return TracerProvider()
TracerProvider()
'''
    assert scan_source(source) == ((6, "TracerProvider"), (7, "TracerProvider"))


def test_optional_branches_preserve_possible_bootstrap_binding() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
if enabled:
    TracerProvider = None
TracerProvider()
try:
    risky()
    TracerProvider = None
except Exception:
    pass
TracerProvider()
'''
    assert scan_source(source) == ((5, "TracerProvider"), (11, "TracerProvider"))


def test_all_branches_shadow_import_without_false_positive() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
if enabled:
    TracerProvider = None
else:
    TracerProvider = lambda: None
TracerProvider()
try:
    risky()
except Exception:
    TracerProvider = None
else:
    TracerProvider = lambda: None
TracerProvider()
'''
    assert scan_source(source) == ()


def test_try_else_does_not_shadow_exception_path_and_finally_does() -> None:
    source = '''
from opentelemetry.sdk.trace import TracerProvider
try:
    risky()
except Exception:
    pass
else:
    TracerProvider = None
TracerProvider()
try:
    risky()
except Exception:
    pass
finally:
    TracerProvider = None
TracerProvider()
'''
    assert scan_source(source) == ((9, "TracerProvider"),)


def test_optional_module_shadow_still_reports_qualified_call() -> None:
    source = '''
import opentelemetry.sdk.trace as sdk
if enabled:
    sdk = None
sdk.TracerProvider()
'''
    assert scan_source(source) == ((5, "TracerProvider"),)


def test_match_branches_preserve_possible_bootstrap_binding() -> None:
    """A shadow in one match arm cannot erase the import on another arm."""
    source = '''
from opentelemetry.sdk.trace import TracerProvider
match selected:
    case "disabled":
        TracerProvider = None
    case _:
        pass
TracerProvider()
'''
    assert scan_source(source) == ((8, "TracerProvider"),)


def test_match_capture_is_a_function_local_binding() -> None:
    """Pattern captures shadow an outer import throughout the function."""
    source = '''
from opentelemetry.sdk.trace import TracerProvider
def choose(selected):
    TracerProvider()
    match selected:
        case TracerProvider:
            pass
'''
    assert scan_source(source) == ()


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
    assert "ref: a87ad6863f0d04e58e3762d0eac8b47188731147" in workflow
    assert "python3 governance/scripts/ci/check_telemetry_ownership.py product" in workflow
