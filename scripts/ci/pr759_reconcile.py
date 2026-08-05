#!/usr/bin/env python3
"""Reconcile PR 759 with protected main and remove this temporary helper."""

from __future__ import annotations

from pathlib import Path
import subprocess


EXPECTED_MAIN_SHA = "f070c504c1cb06891b800d7ab0cf6ac7d3cf8eae"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one Git command from the repository root and capture text output."""
    return subprocess.run(
        args,
        cwd=REPOSITORY_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _resolve_materializer_conflict() -> None:
    """Combine the native-fuzz classifier with the trusted uv implementation."""
    materializer = REPOSITORY_ROOT / "scripts" / "ci" / "materialize_base_python_requirements.py"
    text = materializer.read_text(encoding="utf-8")
    start = text.index("<<<<<<< HEAD\n")
    end = text.index(">>>>>>> origin/main\n", start) + len(">>>>>>> origin/main\n")
    replacement = '''NATIVE_FUZZ_ENGINE_LOCK_NAMES = frozenset({"requirements-atheris.txt"})
TRUSTED_UV_VERSION = "0.12.1"
TRUSTED_UV_ARCHIVE_URL = (
    "https://releases.astral.sh/github/uv/releases/download/0.12.1/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
)
TRUSTED_UV_ARCHIVE_SHA256 = (
    "90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb"
)
TRUSTED_UV_ARCHIVE_MEMBER = "uv-x86_64-unknown-linux-gnu/uv"
TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS = 120
TRUSTED_UV_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
TRUSTED_UV_BINARY_MAX_BYTES = 64 * 1024 * 1024
TRUSTED_UV_VERSION_TIMEOUT_SECONDS = 10


def _is_native_fuzz_engine_lock_name(name: str) -> bool:
    """Return whether a lock installs a native engine used only by fuzz jobs."""
    return name in NATIVE_FUZZ_ENGINE_LOCK_NAMES


class _RejectTrustedUvRedirects(urllib.request.HTTPRedirectHandler):
    """Reject every redirect before urllib issues a request to its target."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        """Fail closed for all redirect status codes and target locations."""
        del request, response, code, message, headers, new_url
        raise RuntimeError("trusted uv archive redirects are forbidden")


@functools.cache
def _install_trusted_uv_url_opener() -> None:
    """Install one process-wide no-proxy, no-redirect opener for the fixed URL."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectTrustedUvRedirects(),
    )
    urllib.request.install_opener(opener)
'''
    materializer.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def _write_combined_changelog() -> None:
    """Write one reviewed changelog that preserves both integrated feature sets."""
    (REPOSITORY_ROOT / "CHANGELOG.md").write_text(
        '''# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Keep the native Atheris fuzz-engine lock in dedicated repository fuzz workflows instead of installing it in the generic OpenCode coverage image; immutable hash-pinned property and regression test locks remain eligible for central coverage materialization.
- Publish bounded, credential-redacted OpenCode coverage setup diagnostics through one shared helper and preserve exact-head, Rust dependency-context, and deterministic LLVM coverage-toolchain contracts.
- Install the version-aligned `libclang-19-dev` C interface and export `LIBCLANG_PATH` in central Rust coverage so bindgen-backed packages cannot fail because the generic LLVM image omitted `libclang`.
- Reject unsafe Strix source-directory overrides before path joining, including traversal, absolute, nested, symlink-expanding, glob, control-character, oversized, and excessive-cardinality values while retaining validated internationalized direct directory names.

### Documentation

- Add APA 7 doctoring records for coverage diagnostics, the generic coverage/native fuzz-engine dependency boundary, the trusted-uv materializer, the Strix NVIDIA fallback and source-directory boundary, and the LLVM coverage toolchain, including exact-base trust models, verification fixtures, limitations, and rollback requirements.
''',
        encoding="utf-8",
    )


def _extend_diagnostics_quality_workflow() -> None:
    """Cover the merged trusted-uv tests and the permanent libclang contract."""
    workflow_path = WORKFLOW_DIRECTORY / "opencode-coverage-diagnostics-ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    extra_paths = '''      - "tests/conftest.py"
      - "tests/test_materialize_uv_export_hash_contract.py"
      - "tests/test_trusted_uv_download_contract.py"
      - "tests/test_trusted_uv_materializer_quality_workflow_contract.py"
      - "tests/test_trusted_uv_portability_and_streaming.py"
      - "tests/test_uv_export_isolation_contract.py"
      - "tests/test_uv_redirect_and_coverage_contract.py"
      - "tests/test_uv_redirect_boundary.py"
      - "tests/test_uv_workspace_fail_closed.py"
      - "tests/test_opencode_libclang_toolchain_contract.py"
'''
    path_anchor = '      - "tests/test_coverage_native_fuzz_lock_boundary.py"\n'
    if workflow.count(path_anchor) != 2:
        raise SystemExit("coverage workflow path anchors drifted")
    workflow = workflow.replace(path_anchor, path_anchor + extra_paths)

    old_pytest = '''            tests/test_coverage_native_fuzz_lock_boundary.py \\
            tests/test_sanitize_github_output_summary.py \\
            tests/test_strix_dependency_security_floor.py \\
            --cov=scripts.ci.coverage_failure_summary \\
'''
    new_pytest = '''            tests/test_coverage_native_fuzz_lock_boundary.py \\
            tests/test_materialize_uv_export_hash_contract.py \\
            tests/test_trusted_uv_download_contract.py \\
            tests/test_trusted_uv_materializer_quality_workflow_contract.py \\
            tests/test_trusted_uv_portability_and_streaming.py \\
            tests/test_uv_export_isolation_contract.py \\
            tests/test_uv_redirect_and_coverage_contract.py \\
            tests/test_uv_redirect_boundary.py \\
            tests/test_uv_workspace_fail_closed.py \\
            tests/test_sanitize_github_output_summary.py \\
            tests/test_strix_dependency_security_floor.py \\
            tests/test_opencode_libclang_toolchain_contract.py \\
            --cov=scripts.ci.coverage_failure_summary \\
'''
    if workflow.count(old_pytest) != 1:
        raise SystemExit("coverage workflow pytest anchor drifted")
    workflow = workflow.replace(old_pytest, new_pytest)

    old_compile = '''            tests/test_coverage_native_fuzz_lock_boundary.py \\
            tests/test_sanitize_github_output_summary.py \\
            tests/test_strix_dependency_security_floor.py
'''
    new_compile = '''            tests/test_coverage_native_fuzz_lock_boundary.py \\
            tests/test_materialize_uv_export_hash_contract.py \\
            tests/test_trusted_uv_download_contract.py \\
            tests/test_trusted_uv_materializer_quality_workflow_contract.py \\
            tests/test_trusted_uv_portability_and_streaming.py \\
            tests/test_uv_export_isolation_contract.py \\
            tests/test_uv_redirect_and_coverage_contract.py \\
            tests/test_uv_redirect_boundary.py \\
            tests/test_uv_workspace_fail_closed.py \\
            tests/test_sanitize_github_output_summary.py \\
            tests/test_strix_dependency_security_floor.py \\
            tests/test_opencode_libclang_toolchain_contract.py
'''
    if workflow.count(old_compile) != 1:
        raise SystemExit("coverage workflow compile anchor drifted")
    workflow_path.write_text(workflow.replace(old_compile, new_compile), encoding="utf-8")


def _provision_libclang() -> None:
    """Install and verify the version-aligned Clang C interface in the image."""
    workflow_path = WORKFLOW_DIRECTORY / "opencode-review-dispatch.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    package_old = "              llvm-19 " + chr(92) + "\n"
    package_new = "              libclang-19-dev " + chr(92) + "\n" + package_old
    if package_new not in workflow:
        if workflow.count(package_old) != 1:
            raise SystemExit("expected one llvm-19 package declaration")
        workflow = workflow.replace(package_old, package_new, 1)

    env_old = "          ENV LLVM_COV=/usr/bin/llvm-cov-19\n"
    env_new = "          ENV LIBCLANG_PATH=/usr/lib/llvm-19/lib\n" + env_old
    if env_new not in workflow:
        if workflow.count(env_old) != 1:
            raise SystemExit("expected one LLVM_COV declaration")
        workflow = workflow.replace(env_old, env_new, 1)

    probe_old = '          RUN test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"\n'
    probe_new = (
        '          RUN test -d "$LIBCLANG_PATH" \\\n'
        '            && find "$LIBCLANG_PATH" -maxdepth 1 '
        "\\( -type f -o -type l \\) -name 'libclang.so*' "
        '-print -quit | grep -q . \\\n'
        '            && test -x "$LLVM_COV" \\\n'
        '            && test -x "$LLVM_PROFDATA"\n'
    )
    if probe_new not in workflow:
        if workflow.count(probe_old) != 1:
            raise SystemExit("expected one LLVM executable probe")
        workflow = workflow.replace(probe_old, probe_new, 1)
    workflow_path.write_text(workflow, encoding="utf-8")

    test_path = REPOSITORY_ROOT / "tests" / "test_opencode_libclang_toolchain_contract.py"
    test_path.write_text(
        '''"""Regression contract for the central Rust bindgen toolchain."""

from pathlib import Path


def test_opencode_coverage_image_provisions_bindgen_libclang() -> None:
    """Keep bindgen-backed Rust packages executable in central coverage."""
    workflow = Path(
        ".github/workflows/opencode-review-dispatch.yml"
    ).read_text(encoding="utf-8")
    assert "              libclang-19-dev " + chr(92) in workflow
    assert "ENV LIBCLANG_PATH=/usr/lib/llvm-19/lib" in workflow
    assert 'find "$LIBCLANG_PATH" -maxdepth 1' in workflow
    assert "-name 'libclang.so*'" in workflow
''',
        encoding="utf-8",
    )


def _extend_doctoring() -> None:
    """Record the libclang prerequisite and primary package references."""
    path = REPOSITORY_ROOT / "docs" / "doctoring" / "opencode-llvm-coverage-toolchain.md"
    text = path.read_text(encoding="utf-8")
    section = '''

## Bindgen and libclang compatibility boundary

`llvm-19` provides versioned coverage executables, but a Rust crate that
creates bindings through `bindgen` also needs the Clang C interface at build
time. The central image therefore installs the matching `libclang-19-dev`
package, exports `LIBCLANG_PATH=/usr/lib/llvm-19/lib`, and fails the trusted
image build unless a regular file or symlink matching `libclang.so*` is
present. This is an infrastructure prerequisite only; repository Fuzz and
package-specific native-toolchain gates remain independently required.

Debian Project. (2026). *libclang-19-dev: Clang library—Development package*.
Debian Packages. Retrieved August 5, 2026, from
https://packages.debian.org/trixie/libclang-19-dev

Ubuntu. (2026). *libclang-19-dev in noble-updates*. Ubuntu Packages. Retrieved
August 5, 2026, from https://packages.ubuntu.com/noble-updates/libclang-19-dev
'''
    if "## Bindgen and libclang compatibility boundary" not in text:
        path.write_text(text.rstrip() + section + "\n", encoding="utf-8")


def _extend_combined_coverage_test() -> None:
    """Require the PR quality workflow to execute the inherited uv contracts."""
    path = REPOSITORY_ROOT / "tests" / "test_coverage_materializer_failure_diagnostics.py"
    source = path.read_text(encoding="utf-8")
    name = "test_diagnostics_quality_gate_covers_the_combined_uv_materializer_surface"
    if name in source:
        return
    source += '''


def test_diagnostics_quality_gate_covers_the_combined_uv_materializer_surface() -> None:
    """The PR-specific gate must cover merged trusted-uv production branches."""
    repository_root = Path(__file__).resolve().parents[1]
    workflow = (
        repository_root
        / ".github"
        / "workflows"
        / "opencode-coverage-diagnostics-ci.yml"
    ).read_text(encoding="utf-8")
    required_uv_tests = (
        "tests/test_materialize_uv_export_hash_contract.py",
        "tests/test_trusted_uv_download_contract.py",
        "tests/test_trusted_uv_materializer_quality_workflow_contract.py",
        "tests/test_trusted_uv_portability_and_streaming.py",
        "tests/test_uv_export_isolation_contract.py",
        "tests/test_uv_redirect_and_coverage_contract.py",
        "tests/test_uv_redirect_boundary.py",
        "tests/test_uv_workspace_fail_closed.py",
    )
    for required_test_path in required_uv_tests:
        assert workflow.count(required_test_path) == 4
    assert "--cov=scripts.ci.materialize_base_python_requirements" in workflow
    assert "--cov-branch" in workflow
    assert "--cov-fail-under=100" in workflow
'''
    path.write_text(source, encoding="utf-8")


def _remove_temporary_files() -> None:
    """Remove every PR-specific writer and this helper from the final tree."""
    for path in WORKFLOW_DIRECTORY.iterdir():
        if "pr759" in path.name.lower() or path.name == "export-pr759-current-three-way.yml":
            path.unlink(missing_ok=True)
    Path(__file__).unlink(missing_ok=True)


def main() -> None:
    """Merge, resolve, harden, and stage the exact reviewed PR 759 tree."""
    _run("git", "fetch", "--no-tags", "origin", "main")
    main_sha = _run("git", "rev-parse", "origin/main").stdout.strip()
    if main_sha != EXPECTED_MAIN_SHA:
        raise SystemExit(f"protected main moved: {main_sha}")
    merge = _run("git", "merge", "--no-ff", "--no-commit", "origin/main", check=False)
    if merge.returncode == 0:
        raise SystemExit("expected the reviewed two-file conflict set")
    unresolved = set(
        _run("git", "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
    )
    expected = {"CHANGELOG.md", "scripts/ci/materialize_base_python_requirements.py"}
    if unresolved != expected:
        raise SystemExit(f"unexpected merge conflict set: {sorted(unresolved)}")
    _resolve_materializer_conflict()
    _write_combined_changelog()
    _extend_diagnostics_quality_workflow()
    _provision_libclang()
    _extend_doctoring()
    _extend_combined_coverage_test()
    _remove_temporary_files()
    _run("git", "add", "-A")
    if _run("git", "diff", "--name-only", "--diff-filter=U").stdout.strip():
        raise SystemExit("unresolved merge paths remain")


if __name__ == "__main__":
    main()
