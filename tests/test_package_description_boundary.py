"""Contract for the package-description boundary gate.

A repository README may link internal design records; a package description
may not. ``scripts/ci/package_description_boundary.py`` reads the description
a registry will actually render - PKG-INFO from a built sdist, METADATA from a
wheel - rather than the README on disk, because those are what PyPI shows.

Every expectation below was taken from a real published artifact: the findings
in ``fast_mlsirm-0.11.3.tar.gz`` on PyPI are what motivated the gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import io
from pathlib import Path

import pytest

_SCRIPT = Path("scripts/ci/package_description_boundary.py")


def _module():
    """Load the gate as a module without installing it.

    The module is registered in ``sys.modules`` before execution because
    ``@dataclass`` resolves its own module there while the class body runs.
    """
    name = "package_description_boundary"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sdist(tmp_path: Path, description: str) -> Path:
    """Build a minimal sdist whose PKG-INFO carries ``description``."""
    pkg_info = (
        "Metadata-Version: 2.1\n"
        "Name: example\n"
        "Version: 1.0.0\n"
        "Description-Content-Type: text/markdown\n"
        "\n"
        f"{description}"
    ).encode("utf-8")
    path = tmp_path / "example-1.0.0.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("example-1.0.0/PKG-INFO")
        info.size = len(pkg_info)
        archive.addfile(info, io.BytesIO(pkg_info))
    return path


def test_clean_description_passes(tmp_path: Path) -> None:
    """An absolute-linked, user-facing description is not a finding."""
    module = _module()
    dist = _sdist(tmp_path, "# example\n\nSee the [guide](https://example.com/guide).\n")
    assert module.main(["--dist", str(dist)]) == 0


def test_relative_link_blocks(tmp_path: Path) -> None:
    """A link that works on GitHub is a 404 on the registry page."""
    module = _module()
    dist = _sdist(tmp_path, "See [the design](docs/design.md) and [LICENSE](LICENSE).\n")
    assert module.main(["--dist", str(dist)]) == 1


def test_absolute_and_anchor_links_are_not_findings(tmp_path: Path) -> None:
    """Only links a registry cannot resolve count."""
    module = _module()
    description = (
        "[docs](https://github.com/o/r/blob/main/docs/a.md) "
        "[top](#overview) [mail](mailto:x@example.com)\n"
    )
    assert module.inspect(description).findings == []


def test_internal_working_records_advise_and_adr_says_nothing() -> None:
    """The directory name cannot decide what a repository keeps there.

    The central repository files operational incident records under
    docs/doctoring/; pg-llm-batch files operator documentation there that a
    package user genuinely needs. So this reports and does not block. A
    repo-relative link into such a directory is still blocked, by relative-link,
    which is the mechanical defect.
    """
    module = _module()
    internal = module.inspect(
        "see https://github.com/o/r/blob/main/docs/superpowers/plans/x.md\n"
    )
    assert [(f.rule, f.blocking) for f in internal.findings] == [
        ("internal-working-record", False)
    ]
    adr = module.inspect("see https://github.com/o/r/blob/main/docs/adr/0007-x.md\n")
    assert adr.findings == []


def test_relative_link_into_a_working_record_still_blocks() -> None:
    """Advising on the directory must not stop the dead-link rule firing."""
    module = _module()
    rules = {
        (f.rule, f.blocking)
        for f in module.inspect("see [plan](docs/superpowers/plans/x.md)\n").findings
    }
    assert ("relative-link", True) in rules


def test_monetary_target_blocks_and_vocabulary_only_advises() -> None:
    """A deal value is never a product feature; vocabulary can be one.

    The organization already forbids gating product evidence on a deal value, so
    monetary-target blocks. Go-to-market wording cannot be judged mechanically:
    contextual-orchestrator genuinely ships ``/api/v1/commercial_readiness/latest``
    and wardnet's crate genuinely computes commercial readiness snapshots, so the
    same words are the product there. That rule advises instead of blocking.
    """
    module = _module()
    findings = module.inspect(
        "A KRW 2,000,000,000 commercial readiness gate for buyer packet review.\n"
    ).findings
    by_rule = {f.rule: f for f in findings}
    assert by_rule["monetary-target"].blocking is True
    assert by_rule["go-to-market-vocabulary"].blocking is False


def test_strict_promotes_the_advisory_rules(tmp_path: Path) -> None:
    """A repo that wants the judgement rules enforced can ask for it."""
    module = _module()
    dist = _sdist(tmp_path, "A commercial readiness gate.\n")
    assert module.main(["--dist", str(dist)]) == 0
    assert module.main(["--dist", str(dist), "--strict"]) == 1


def test_adr_under_a_planning_directory_is_not_a_working_record() -> None:
    """An ADR is a public design record wherever the repository files it.

    contextual-orchestrator keeps its ADRs under ``docs/planning/adrs/``; the
    directory prefix must not turn them into findings.
    """
    module = _module()
    adr = module.inspect(
        "See [ADR 0001](https://github.com/o/r/blob/main/docs/planning/adrs/0001-x.md).\n"
    )
    assert [f.rule for f in adr.findings] == []
    plan = module.inspect(
        "See [plan](https://github.com/o/r/blob/main/docs/planning/2026-07-02-x.md).\n"
    )
    assert [(f.rule, f.blocking) for f in plan.findings] == [
        ("internal-working-record", False)
    ]


def test_quoted_source_path_blocks() -> None:
    """A module path is plumbing, not something the reader can act on."""
    module = _module()
    assert [f.rule for f in module.inspect("`src/pkg/steward_review.py` holds it.\n").findings] == [
        "source-path"
    ]


def test_allow_downgrades_a_rule_without_hiding_it(tmp_path: Path) -> None:
    """A repo mid-migration can report a rule without failing on it."""
    module = _module()
    dist = _sdist(tmp_path, "See [the design](docs/design.md).\n")
    assert module.main(["--dist", str(dist), "--allow", "relative-link"]) == 0


def test_json_report_records_every_finding(tmp_path: Path) -> None:
    """CI needs the machine-readable form, not only the printed lines."""
    module = _module()
    dist = _sdist(tmp_path, "[a](docs/a.md) and `src/pkg/x.py`\n")
    out = tmp_path / "report.json"
    module.main(["--dist", str(dist), "--json", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert {f["rule"] for f in report["findings"]} == {"relative-link", "source-path"}


def test_missing_metadata_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """An unreadable distribution must never look like a clean one."""
    module = _module()
    empty = tmp_path / "empty-1.0.0.tar.gz"
    with tarfile.open(empty, "w:gz"):
        pass
    assert module.main(["--dist", str(empty)]) == 2


def test_readme_fallback_is_available_before_a_first_release(tmp_path: Path) -> None:
    """A repo with no distribution yet can still be gated on its README."""
    module = _module()
    readme = tmp_path / "README.md"
    readme.write_text("[design](docs/design.md)\n", encoding="utf-8")
    assert module.main(["--readme", str(readme)]) == 1


_WORKFLOW = Path(".github/workflows/package-description-boundary.yml")


def _workflow() -> dict:
    """Parse the reusable gate workflow."""
    import yaml

    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_is_callable_only() -> None:
    """A required-workflow ruleset must not be able to admit a build-and-run file."""
    assert set(_workflow()[True]) == {"workflow_call"}


def test_workflow_checks_out_the_gate_at_its_own_commit() -> None:
    """The caller must run the gate revision it pinned, not whatever main holds."""
    steps = _workflow()["jobs"]["package-description-boundary"]["steps"]
    central = [s for s in steps if (s.get("with") or {}).get("repository") == "ContextualWisdomLab/.github"]
    assert central, "the gate is never checked out"
    assert central[0]["with"]["ref"] == "${{ github.workflow_sha }}"
    assert central[0]["with"]["persist-credentials"] is False


def test_workflow_pins_every_action_to_a_commit_sha() -> None:
    """A mutable tag in a workflow every consumer inherits is a supply-chain hole."""
    for line in _WORKFLOW.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith(("- uses:", "uses:")):
            continue
        reference = stripped.partition("uses:")[2].strip().split()[0]
        version = reference.partition("@")[2]
        assert len(version) == 40 and all(c in "0123456789abcdef" for c in version), stripped


def test_workflow_declares_least_privilege() -> None:
    """The gate only reads code."""
    assert _workflow()["permissions"] == {"contents": "read"}


def test_workflow_falls_back_to_readme_before_a_first_release() -> None:
    """A repo with no distribution yet is still gated."""
    steps = _workflow()["jobs"]["package-description-boundary"]["steps"]
    check = [s for s in steps if "package_description_boundary.py" in s.get("run", "")]
    assert check, "the gate is never invoked"
    assert "--readme" in check[0]["run"]
    assert "--dist" in check[0]["run"]
