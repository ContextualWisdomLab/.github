"""Actual artifact license bytes exercise the same dependency consumer."""

import hashlib
import json
from pathlib import Path
import re

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci import spdx_license_policy as policy
from tests.test_release_dependency_gate import _python_evidence

ROOT = Path(__file__).parent / "fixtures" / "release_license_texts"
ROWS = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
TEXTS = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["package"])
def test_actual_whole_text_and_consumer(row):
    """Whole text matches recorded bytes and the declared-license caller."""
    raw = TEXTS[row["fixture"]].encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == row["raw_sha256"]
    text = raw.decode("utf-8")
    normalized = re.sub(r"[ \t\r\n]+", " ", text).strip(" \t\r\n")
    assert hashlib.sha256(normalized.encode()).hexdigest() == row["normalized_sha256"]
    assert policy.recognize_license_text(text) == frozenset({row["identifier"]})
    # This synthetic declaration exercises the recognizer, and does not claim
    # that atheris's actual missing metadata has been repaired.
    evidence = _python_evidence(license_expression=row["identifier"],
                                license_texts={"LICENSE": text})
    failures, _, _ = gate.evaluate_dependency_license(evidence, row["package"], None)
    assert failures == []


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["package"])
@pytest.mark.parametrize("placement", ["prefix", "suffix", "body", "notice"])
def test_additional_condition_and_multifile_are_rejected(row, placement):
    """No additional condition can inherit the recognized full-text digest."""
    text = TEXTS[row["fixture"]]
    restriction = "Commercial use is prohibited. Academic research only."
    files = {"LICENSE": text}
    if placement == "prefix":
        files["LICENSE"] = restriction + "\n" + text
    elif placement == "suffix":
        files["LICENSE"] = text + "\n" + restriction
    elif placement == "body":
        middle = len(text) // 2
        files["LICENSE"] = text[:middle] + restriction + text[middle:]
    else:
        files["NOTICE"] = restriction
    failures, _, _ = gate.evaluate_dependency_license(
        _python_evidence(license_expression=row["identifier"], license_texts=files),
        row["package"], None)
    assert [f.code for f in failures] == [policy.LICENSE_TEXT_UNVERIFIED]


def test_atheris_missing_declaration_is_not_auto_repaired():
    """Identifying bundled Apache text does not manufacture package metadata."""
    row = next(r for r in ROWS if r["package"] == "atheris@3.1.0")
    failures, decision, _ = gate.evaluate_dependency_license(
        _python_evidence(license_expression=None, license="", classifiers=[],
                         license_texts={"LICENSE": TEXTS[row["fixture"]]}),
        row["package"], None)
    assert not decision.allowed
    assert failures


def test_allocator_dual_licence_uses_both_actual_archive_texts():
    rows = [row for row in ROWS if row['package'] == 'allocator-api2@0.2.21']
    evidence = _python_evidence(
        license_expression='MIT OR Apache-2.0',
        license_texts={row['member']: TEXTS[row['fixture']] for row in rows},
    )
    failures, decision, _ = gate.evaluate_dependency_license(
        evidence, 'cargo/allocator-api2@0.2.21',
        {'chosen': 'MIT', 'rationale': 'Inspected both archive licence texts; retain the MIT permission notice.'},
    )
    assert failures == []
    assert decision.allowed
    failures, _, _ = gate.evaluate_dependency_license(evidence, 'cargo/allocator-api2@0.2.21', None)
    assert policy.LICENSE_SELECTION_REQUIRED in {failure.code for failure in failures}


@pytest.mark.parametrize("row", [r for r in json.loads((ROOT / "reference_provenance.json").read_text())
                                  if r["package"].startswith("android_system_properties@")],
                         ids=lambda row: row["package"])
@pytest.mark.parametrize("mutation", [None, "no-mit", "notice-only", "changed-notice",
                                      "apache-choice", "pypi", "and-expression", "no-choice"])
def test_android_apache_notice_does_not_supply_a_full_grant(row, mutation):
    text = TEXTS[row["fixture"]]
    assert hashlib.sha256(text.encode()).hexdigest() == row["raw_sha256"]
    normalized = re.sub(r"[ \t\r\n]+", " ", text).strip(" \t\r\n")
    assert hashlib.sha256(normalized.encode()).hexdigest() == row["normalized_sha256"]
    assert policy.recognize_license_text(text) is None
    texts = {"LICENSE-MIT": TEXTS["android_system_properties-0.1.6-LICENSE-MIT.txt"],
             "LICENSE-APACHE": text}
    if mutation in {"no-mit", "notice-only"}:
        del texts["LICENSE-MIT"]
    if mutation == "changed-notice":
        texts["LICENSE-APACHE"] += "Commercial redistribution requires additional permission."
    expression = "MIT AND Apache-2.0" if mutation == "and-expression" else "MIT OR Apache-2.0"
    selection = {"chosen": "Apache-2.0" if mutation == "apache-choice" else "MIT",
                 "rationale": "Read complete MIT grant and the separate Apache reference notice."}
    if mutation == "no-choice":
        selection = None
    evidence = _python_evidence(license_expression=expression, license_texts=texts,
                                ecosystem="pypi" if mutation == "pypi" else "cargo")
    failures, decision, _ = gate.evaluate_dependency_license(evidence, row["package"], selection)
    assert (decision.allowed and not failures) == (mutation is None)
    if mutation == "apache-choice":
        assert policy.LICENSE_TEXT_MISSING in {failure.code for failure in failures}


@pytest.mark.parametrize("mutation", [None, "checksum", "subject", "filename", "template", "no-apache",
                                      "changed-apache", "mit-choice", "no-choice", "pypi", "denied"])
def test_unarray_template_is_only_reference_for_exact_apache_choice(mutation):
    row = next(r for r in json.loads((ROOT / "reference_provenance.json").read_text())
               if r["package"] == "unarray@0.1.4")
    template = TEXTS[row["fixture"]]
    assert hashlib.sha256(template.encode()).hexdigest() == row["raw_sha256"]
    assert policy.recognize_license_text(template) is None
    apache = TEXTS[row["required_grant_fixture"]]
    assert policy.recognize_license_text(apache) == frozenset({"Apache-2.0"})
    files = {row["member"]: template, "unarray-0.1.4/LICENSE-APACHE": apache}
    subject = "cargo/unarray@0.1.4"
    evidence = _python_evidence(ecosystem="cargo", license_expression="MIT OR Apache-2.0",
                                license_texts=files, source_sha256=row["artifact_sha256"])
    selection = {"chosen": "Apache-2.0", "rationale": "Read exact README and full Apache grant; retain template unchanged."}
    if mutation == "checksum":
        evidence["source_sha256"] = "0" * 64
    elif mutation == "subject":
        subject = "cargo/unarray@0.1.5"
    elif mutation == "filename":
        files["OTHER-MIT"] = files.pop(row["member"])
    elif mutation == "template":
        files[row["member"]] += "Commercial use prohibited."
    elif mutation == "no-apache":
        del files["unarray-0.1.4/LICENSE-APACHE"]
    elif mutation == "changed-apache":
        files["unarray-0.1.4/LICENSE-APACHE"] += "Commercial use prohibited."
    elif mutation == "mit-choice":
        selection["chosen"] = "MIT"
    elif mutation == "no-choice":
        selection = None
    elif mutation == "pypi":
        evidence["ecosystem"] = "pypi"
    elif mutation == "denied":
        files["EXTRA-LICENSE"] = "GNU GENERAL PUBLIC LICENSE Version 3"
    failures, decision, _ = gate.evaluate_dependency_license(evidence, subject, selection)
    assert (decision.allowed and not failures) == (mutation is None)
    assert policy.recognize_license_text(template) is None


@pytest.mark.parametrize("mutation", [None, "apache-choice", "mit-only", "no-choice", "no-unicode",
                                      "changed-unicode", "no-main-grant", "checksum", "subject", "pypi"])
def test_regex_unicode_grant_remains_an_independent_obligation(mutation):
    files = {f"regex-syntax-0.8.11/{name}": TEXTS[f"regex-syntax-0.8.11-{Path(name).name}.txt"]
             for name in ("LICENSE-MIT", "LICENSE-APACHE", "src/unicode_tables/LICENSE-UNICODE")}
    evidence = _python_evidence(ecosystem="cargo", license_expression="MIT OR Apache-2.0",
                                license_texts=files,
                                source_sha256="d6f6ff9a378485b298a5286656da665ba74413d36db0979633275d2e708145d4")
    subject = "cargo/regex-syntax@0.8.11"
    choice = {"chosen": "MIT AND Unicode-DFS-2016", "rationale": "Retain original main-code and independent Unicode notices."}
    if mutation == "apache-choice":
        choice["chosen"] = "Apache-2.0 AND Unicode-DFS-2016"
    elif mutation == "mit-only":
        choice["chosen"] = "MIT"
    elif mutation == "no-choice":
        choice = None
    elif mutation == "no-unicode":
        del files["regex-syntax-0.8.11/src/unicode_tables/LICENSE-UNICODE"]
    elif mutation == "changed-unicode":
        files["regex-syntax-0.8.11/src/unicode_tables/LICENSE-UNICODE"] += "Commercial use prohibited."
    elif mutation == "no-main-grant":
        del files["regex-syntax-0.8.11/LICENSE-MIT"]
    elif mutation == "checksum":
        evidence["source_sha256"] = "0" * 64
    elif mutation == "subject":
        subject = "cargo/regex-syntax@0.8.12"
    elif mutation == "pypi":
        evidence["ecosystem"] = "pypi"
    failures, decision, _ = gate.evaluate_dependency_license(evidence, subject, choice)
    assert (decision.allowed and not failures) == (mutation in {None, "apache-choice"})


@pytest.mark.parametrize("mutation", [None, "mit-only", "no-choice", "missing-package", "missing-sun",
                                      "missing-bsd", "missing-mit-source", "changed-source", "changed-package",
                                      "checksum", "subject", "pypi", "extra-denied"])
def test_libm_complete_source_members_preserve_independent_notices(mutation):
    raw = (ROOT / "libm-0.2.16.crate").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "b6d2cec3eae94f9f509c767b45932f1ada8350c4bdb85af2fcab4a3c14807981"
    evidence = gate.archive_license_evidence(raw, "cargo")
    evidence.update(ecosystem="cargo", license="MIT")
    files = evidence["license_texts"]
    assert len(files) == 70
    subject = "cargo/libm@0.2.16"
    choice = {"chosen": "MIT AND BSD-2-Clause AND SunPro",
              "rationale": "Retain complete package and original file-specific notices."}
    if mutation == "mit-only":
        choice["chosen"] = "MIT"
    elif mutation == "no-choice":
        choice = None
    elif mutation == "missing-package":
        del files["libm-0.2.16/LICENSE.txt"]
    elif mutation == "missing-sun":
        del files["libm-0.2.16/src/math/acos.rs"]
    elif mutation == "missing-bsd":
        del files["libm-0.2.16/src/math/exp2.rs"]
    elif mutation == "missing-mit-source":
        del files["libm-0.2.16/src/math/cbrt.rs"]
    elif mutation == "changed-source":
        files["libm-0.2.16/src/math/exp2f.rs"] += "// Commercial use prohibited."
    elif mutation == "changed-package":
        files["libm-0.2.16/LICENSE.txt"] += "Commercial use prohibited."
    elif mutation == "checksum":
        evidence["source_sha256"] = "0" * 64
    elif mutation == "subject":
        subject = "cargo/libm@0.2.17"
    elif mutation == "pypi":
        evidence["ecosystem"] = "pypi"
    elif mutation == "extra-denied":
        files["EXTRA-LICENSE"] = "GNU GENERAL PUBLIC LICENSE Version 3"
    failures, decision, _ = gate.evaluate_dependency_license(evidence, subject, choice)
    assert (decision.allowed and not failures) == (mutation is None)
    if mutation is None:
        assert decision.selected == "MIT AND BSD-2-Clause AND SunPro"


def test_known_profiling_upstream_grant_does_not_waive_missing_crate_text():
    text = TEXTS["profiling-1.0.18-upstream-LICENSE-MIT.txt"]
    assert policy.recognize_license_text(text) == frozenset({"MIT"})
    evidence = _python_evidence(ecosystem="cargo", license_expression="MIT OR Apache-2.0",
                                license_texts={},
                                source_sha256="3d595e54a326bc53c1c197b32d295e14b169e3cfeaa8dc82b529f947fba6bcf5")
    failures, _, _ = gate.evaluate_dependency_license(
        evidence, "cargo/profiling@1.0.18",
        {"chosen": "MIT", "rationale": "Upstream full text known; captured crate still lacks it."})
    assert policy.LICENSE_TEXT_MISSING in {failure.code for failure in failures}


@pytest.mark.parametrize("mutation", [None, "changed-notice", "missing-notice", "symlink-notice",
                                      "wrong-upstream", "wrong-notice-digest", "captured-choice",
                                      "wrong-archive", "no-source", "truncated-notice", "missing-input-grant"])
@pytest.mark.parametrize("package,version,repository,upstream_commit", [
    ("profiling", "1.0.18", "aclysma/profiling", "8271551172eb6fa4cba47369aedd93790c623df9"),
    ("jni-sys-macros", "0.4.1", "jni-rs/jni-sys", "64d77b7a5f119d7b55b4e2c169a4668067ff59e6"),
    ("gl_generator", "0.14.0", "brendanzab/gl-rs", "ea503e8d5fb6d73c6030e6191ce738cd3bf3433e"),
    ("spirv", "0.4.0+sdk-1.4.341.0", "gfx-rs/rspirv", "8afc3d0ac8e158128cd1410bb2e4b4c26ab11bb4"),
])
def test_supplement_uses_real_source_git_blob_in_whole_gate(tmp_path, mutation, package, version, repository, upstream_commit):
    import os
    import subprocess
    from tests.test_release_dependency_gate import build_capture, _cargo_evidence, _write

    capture = build_capture(tmp_path / "capture")
    raw = (ROOT / f"{package}-{version}.crate").read_bytes()
    archive_sha = hashlib.sha256(raw).hexdigest()
    source = (tmp_path / "source").resolve()
    source.mkdir()
    chosen = ("Apache-2.0 AND MIT-Khronos-old" if package == "spirv" else
              "Apache-2.0" if package == "gl_generator" else "MIT")
    expression = "Apache-2.0" if package in {"gl_generator", "spirv"} else "MIT OR Apache-2.0"
    names = ("LICENSE",) if package == "gl_generator" else ("LICENSE-MIT", "LICENSE-APACHE")
    if package == "spirv":
        grant_content = TEXTS["spirv-upstream-APACHE.txt"].encode()
        upstream = [{"url": f"https://raw.githubusercontent.com/{repository}/{upstream_commit}/LICENSE",
                     "sha256": hashlib.sha256(grant_content).hexdigest()},
                    {"url": "https://raw.githubusercontent.com/KhronosGroup/SPIRV-Headers/04f10f650d514df88b76d25e83db360142c7b174/LICENSE",
                     "sha256": hashlib.sha256((ROOT / "spirv-generator-LICENSE").read_bytes()).hexdigest()}]
    else:
        grant_content = b"\n\n".join(TEXTS[f"{package}-{version}-upstream-{name}.txt"].encode() for name in names)
        upstream = [{"url": f"https://raw.githubusercontent.com/{repository}/{upstream_commit}/{name}",
                     "sha256": hashlib.sha256(TEXTS[f"{package}-{version}-upstream-{name}.txt"].encode()).hexdigest()}
                    for name in names]
    content = ((ROOT / f"{package}-{version}-complete-notice.txt").read_bytes()
               if package in {"gl_generator", "spirv"} else grant_content)
    notice_path = f"python/fast_mlsirm/_licenses/{package}-{version}.txt"
    notice = source / notice_path
    notice.parent.mkdir(parents=True)
    notice.write_bytes(content)
    choice = {"ecosystem": "cargo", "name": package, "version": version, "chosen": chosen,
              "rationale": "Preserve exact immutable upstream grants in release source.", "archive_sha256": archive_sha,
              "bundled_notice": {"path": notice_path, "sha256": hashlib.sha256(content).hexdigest()},
              "upstream_licenses": upstream}
    if mutation == "changed-notice":
        notice.write_bytes(content + b"Commercial use prohibited.")
    elif mutation == "truncated-notice":
        notice.write_bytes(grant_content if package in {"gl_generator", "spirv"} else content[:-1])
    elif mutation == "missing-notice":
        notice.unlink()
    elif mutation == "symlink-notice":
        notice.unlink()
        os.symlink("/missing", notice)
    elif mutation == "missing-input-grant":
        choice["upstream_licenses"].pop()
    elif mutation == "wrong-upstream":
        choice["upstream_licenses"][0]["url"] = "https://example.invalid/LICENSE-MIT"
    elif mutation == "wrong-notice-digest":
        choice["bundled_notice"]["sha256"] = "0" * 64
    _write(source / "docs/release-license-selections.json", [choice])
    (source / "Cargo.toml").write_text('[package]\nname="fast-mlsirm"\nversion="0.11.5"\n')
    lock = (capture / "cargo/Cargo.lock").read_text()
    old_checksum = __import__("tomllib").loads(lock)["package"][1]["checksum"]
    lock = lock.replace('name = "greencrate"', f'name = "{package}"').replace('version = "0.1.0"', f'version = "{version}"').replace(old_checksum, archive_sha)
    (source / "Cargo.lock").write_text(lock)
    (capture / "cargo/Cargo.lock").write_text(lock)
    metadata = json.loads((capture / "cargo/metadata.json").read_text())
    metadata["workspace_root"] = str(source)
    metadata["packages"][0]["manifest_path"] = str(source / "Cargo.toml")
    metadata["packages"][1].update(name=package, version=version, license=expression)
    _write(capture / "cargo/metadata.json", metadata)
    for args in [("init", "-q"), ("add", "."), ("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
                                               "-c", "commit.gpgsign=false", "commit", "-qm", "source")]:
        subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True)
    sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    release = json.loads((capture / "release.json").read_text())
    release["source_sha"] = sha
    _write(capture / "release.json", release)
    gate.capture_license_selections(source, sha, capture)
    if mutation == "captured-choice":
        copied = json.loads((capture / "license-selections.json").read_text())
        copied[0]["rationale"] = "Forged captured rationale"
        _write(capture / "license-selections.json", copied)
    for folder in ("archives", "evidence", "strix/fixtures", "strix/bindings"):
        for path in (capture / folder).glob("cargo__greencrate__*"):
            path.unlink()
    dependency = gate.Dependency("cargo", package, version)
    evidence = _cargo_evidence(**gate.archive_license_evidence(raw, "cargo"), name=package, version=version,
                               license_expression=expression)
    if mutation == "wrong-archive":
        evidence["source_sha256"] = "0" * 64
    (capture / "archives" / f"{dependency.slug}.archive").write_bytes(raw)
    _write(capture / "evidence" / f"{dependency.slug}.json", evidence)
    _write(capture / "strix/fixtures" / f"{dependency.slug}.json", gate.build_fixture(dependency, evidence))
    # This stage makes no Strix acceptance claim; it still runs complete capture,
    # lock/graph/source/member/fixture/selection reconciliation before licences.
    report = gate.gate(capture, stage=gate.LICENSE_STAGE, source_root=None if mutation == "no-source" else source)
    assert report.passed == (mutation is None), report.to_json()
    if mutation is None:
        row = next(r for r in report.dependencies if r["key"] == dependency.key)
        assert row["license_member_sha256"] == {}
        assert row["source_license_notice"]["source_sha"] == sha
        assert row["source_license_notice"]["upstream_licenses"] == choice["upstream_licenses"]


@pytest.mark.parametrize("mutation", [None, "apache-only", "missing-input-grant", "changed-input-grant"])
def test_spirv_generated_input_obligation_is_independent(mutation):
    """A complete Apache grant cannot replace the generated-input grant."""
    raw = (ROOT / "spirv-0.4.0+sdk-1.4.341.0.crate").read_bytes()
    evidence = {**gate.archive_license_evidence(raw, "cargo"), "ecosystem": "cargo", "license": "Apache-2.0"}
    evidence["license_texts"] = {"upstream/Apache": TEXTS["spirv-upstream-APACHE.txt"],
                               "upstream/Khronos": TEXTS["spirv-Khronos-applicable-grant.txt"]}
    selected = "Apache-2.0 AND MIT-Khronos-old"
    if mutation == "apache-only":
        selected = "Apache-2.0"
    elif mutation == "missing-input-grant":
        del evidence["license_texts"]["upstream/Khronos"]
    elif mutation == "changed-input-grant":
        evidence["license_texts"]["upstream/Khronos"] += "Commercial redistribution prohibited."
    failures, decision, _ = gate.evaluate_dependency_license(
        evidence, "cargo/spirv@0.4.0+sdk-1.4.341.0", {"chosen": selected, "rationale": "Retain both grants."})
    assert (decision.allowed and not failures) == (mutation is None)


@pytest.mark.parametrize("row", [r for r in json.loads((ROOT / "reference_provenance.json").read_text())
                                  if "archive_license_members" in r], ids=lambda r: r["package"])
@pytest.mark.parametrize("mutation", [None, "notice-only", "changed-notice", "no-mit", "no-apache",
                                      "changed-grant", "pypi", "additional-restriction"])
def test_copyright_references_require_complete_independent_grants(row, mutation):
    files = {}
    for member, proof in row["archive_license_members"].items():
        text = TEXTS[proof["fixture"]]
        assert hashlib.sha256(text.encode()).hexdigest() == proof["raw_sha256"]
        files[member] = text
    reference = files[row["member"]]
    assert policy.recognize_license_text(reference) is None
    assert hashlib.sha256(re.sub(r"[ \t\r\n]+", " ", reference).strip(" \t\r\n").encode()).hexdigest() == row["normalized_sha256"]
    if mutation == "notice-only":
        files = {row["member"]: reference}
    elif mutation == "changed-notice":
        files[row["member"]] += "Commercial redistribution requires permission."
    elif mutation in {"no-mit", "no-apache"}:
        suffix = "/LICENSE-MIT" if mutation == "no-mit" else "/LICENSE-APACHE"
        files = {member: text for member, text in files.items() if not member.endswith(suffix)}
        if mutation == "no-apache":
            files = {member: text for member, text in files.items() if "LLVM-exception" not in member}
    elif mutation == "changed-grant":
        member = next(member for member in files if member.endswith("/LICENSE-MIT"))
        files[member] += "Commercial use is prohibited."
    elif mutation == "additional-restriction":
        files["NOTICE"] = "Commercial use is prohibited."
    evidence = _python_evidence(ecosystem="pypi" if mutation == "pypi" else "cargo",
                                source_sha256=row["artifact_sha256"], license_expression=row["expression"],
                                license_texts=files)
    failures, decision, _ = gate.evaluate_dependency_license(
        evidence, "cargo/" + row["package"], {"chosen": "MIT", "rationale": "Retain reviewed original reference and complete grants."})
    assert (decision.allowed and not failures) == (mutation is None)


@pytest.mark.parametrize("package", ["rustix@1.1.4", "linux-raw-sys@0.12.1"])
def test_copyright_llvm_reference_requires_complete_exception(package):
    row = next(r for r in json.loads((ROOT / "reference_provenance.json").read_text()) if r["package"] == package)
    files = {member: TEXTS[proof["fixture"]] for member, proof in row["archive_license_members"].items()
             if "LLVM-exception" not in member}
    failures, decision, _ = gate.evaluate_dependency_license(
        _python_evidence(ecosystem="cargo", license_expression=row["expression"], license_texts=files),
        "cargo/" + package, {"chosen": "MIT", "rationale": "Negative test: exception body is absent."})
    assert decision.allowed
    assert policy.LICENSE_TEXT_UNVERIFIED in {failure.code for failure in failures}
