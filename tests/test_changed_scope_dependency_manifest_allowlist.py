"""Contract: the `changed-scope` dependency allowlist covers scannable manifests.

`security-scan.yml` runs `osv-scan` and `dependency-review` only when the
`changed-scope` classifier sets `deps=true`, and that flag is restored from a
closed filename allowlist. A dependency introduced through a manifest or
lockfile missing from the list silently skips both supply-chain gates (Strix
MEDIUM finding on `.github#2143`, 2026-09-13). The list must therefore cover
every lockfile the pinned osv-scanner v2.5.1 can scan plus the manifests the
GitHub dependency graph reads. The three gate copies share one byte-identical
classifier block (see `test_docs_only_pr_runner_admission.py`), so this test
reads the line from each copy.
"""

from __future__ import annotations

from pathlib import Path

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github/workflows"
GATE_COPIES = ("security-scan.yml", "sast-semgrep.yml", "strix.yml")

# osv-scanner v2.5.1 `docs/supported_languages_and_lockfiles.md` names, plus
# the manifests that declare dependencies before any lockfile exists.
REQUIRED_MANIFESTS = (
    "requirements*.txt", "pyproject.toml", "uv.lock", "pylock.*.toml", "poetry.lock", "pdm.lock",
    "Pipfile", "Pipfile.lock", "setup.py", "setup.cfg", "environment.yml",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "deno.lock",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "go.work", "go.work.sum",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "gradle.lockfile",
    "buildscript-gradle.lockfile", "libs.versions.toml", "verification-metadata.xml",
    "Gemfile", "Gemfile.lock", "gems.locked", "composer.json", "composer.lock", "conan.lock", "conanfile.txt",
    "packages.lock.json", "packages.config", "deps.json", "Directory.Packages.props",
    "mix.exs", "mix.lock", "pubspec.yaml", "pubspec.lock", "Package.swift", "Package.resolved",
    "Podfile", "Podfile.lock", "renv.lock", "DESCRIPTION", "stack.yaml.lock", "flake.lock", "vcpkg.json",
    "deno.json", "deno.jsonc", "MODULE.bazel", "MODULE.bazel.lock", "WORKSPACE", "WORKSPACE.bazel",
    "maven_install.json", "Manifest.toml", "Project.toml", ".terraform.lock.hcl",
)
REQUIRED_SUFFIX_GLOBS = ("*.csproj", "*.fsproj", "*.vbproj", "*.gemspec", "*.nuspec", "*.MODULE.bazel", "*.tf", "*.tofu")


def _deps_case_line(workflow_name: str) -> str:
    """Return the single `case` pattern line that restores `deps=true`."""
    lines = [
        line.strip()
        for line in (WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8").splitlines()
        if line.rstrip().endswith(") deps=true ;;")
    ]
    assert len(lines) == 1, (workflow_name, len(lines))
    return lines[0]


def test_dependency_allowlist_names_every_scannable_manifest() -> None:
    """Each gate copy lists every manifest at the root and under any directory."""
    for workflow_name in GATE_COPIES:
        patterns = set(_deps_case_line(workflow_name).split(") deps=true")[0].split("|"))
        for manifest in REQUIRED_MANIFESTS:
            assert manifest in patterns, (workflow_name, manifest)
            assert f"*/{manifest}" in patterns, (workflow_name, manifest)
        for glob in REQUIRED_SUFFIX_GLOBS:
            assert glob in patterns, (workflow_name, glob)


def test_dependency_allowlist_is_identical_across_gate_copies() -> None:
    """The allowlist must not drift between the three classifier copies."""
    assert len({_deps_case_line(name) for name in GATE_COPIES}) == 1
