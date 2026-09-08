"""Discover repository-native execution, lint, and security contracts."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any


LANGUAGE_SURFACES = {
    "c_cpp": {
        "extensions": (".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"),
        "manifests": ("CMakeLists.txt", "Makefile", "meson.build"),
    },
    "go": {"extensions": (".go",), "manifests": ("go.mod",)},
    "java": {"extensions": (".java", ".kt", ".kts"), "manifests": ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")},
    "node": {"extensions": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"), "manifests": ("package.json",)},
    "python": {"extensions": (".py",), "manifests": ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "tox.ini", "noxfile.py")},
    "r": {"extensions": (".R", ".r"), "manifests": ("DESCRIPTION", "renv.lock")},
    "ruby": {"extensions": (".rb",), "manifests": ("Gemfile", "*.gemspec")},
    "rust": {"extensions": (".rs",), "manifests": ("Cargo.toml",)},
    "swift": {"extensions": (".swift",), "manifests": ("Package.swift", "*.xcodeproj", "*.xcworkspace")},
}
RUNTIME_NAMES_RE = r"python|node|java|ruby|go|rust|r"
VERSION_RE = re.compile(rf"\b({RUNTIME_NAMES_RE})-version\s*:\s*['\"]?([^'\"\]\[\n#]+)")
MATRIX_RE = re.compile(rf"\b({RUNTIME_NAMES_RE})-version\s*:\s*\[([^\]]+)\]")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Discover review execution contracts.")
    parser.add_argument("--repo-root", default=".", help="Repository root to inspect.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json", help="Output format.")
    return parser.parse_args(argv)


def read_text(path: Path) -> str:
    """Read text with replacement for invalid bytes."""
    return path.read_text(encoding="utf-8", errors="replace")


def relative(path: Path, root: Path) -> str:
    """Return a POSIX path relative to root."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def add_unique(bucket: dict[str, list[str]], key: str, value: str) -> None:
    """Append a unique non-empty value to a bucket."""
    cleaned = value.strip()
    if cleaned and cleaned not in bucket.setdefault(key, []):
        bucket[key].append(cleaned)


def prefix_for(path: Path, root: Path) -> str:
    """Return a shell prefix for commands scoped to a subdirectory."""
    directory = path.parent
    return "" if directory.resolve() == root.resolve() else f"cd {relative(directory, root)} && "


def package_runner(path: Path) -> str:
    """Infer the package manager from lockfiles."""
    if (path.parent / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (path.parent / "yarn.lock").exists():
        return "yarn"
    return "npm"


def add_command_indexes(contracts: dict[str, Any], commands: dict[str, list[str]]) -> None:
    """Copy discovered command groups into top-level indexes."""
    for command_type, values in commands.items():
        index_name = f"{command_type}_commands"
        if index_name in contracts:
            contracts[index_name].extend(values)


def discover_package_json(path: Path, root: Path) -> dict[str, Any]:
    """Discover Node package scripts and engines."""
    data = json.loads(read_text(path))
    scripts = data.get("scripts") or {}
    dependencies = data.get("dependencies") or {}
    dev_dependencies = data.get("devDependencies") or {}
    all_packages = {**dependencies, **dev_dependencies}
    runner = package_runner(path)
    prefix = prefix_for(path, root)
    commands: dict[str, list[str]] = {}
    for name, command in sorted(scripts.items()):
        lowered = f"{name} {command}".lower()
        run = f"{prefix}{runner} run {name}"
        if any(token in lowered for token in ("test", "jest", "vitest", "playwright", "cypress")):
            add_unique(commands, "test", run)
        if any(token in lowered for token in ("coverage", "cov")):
            add_unique(commands, "coverage", run)
        if any(token in lowered for token in ("lint", "eslint", "biome", "prettier", "stylelint")):
            add_unique(commands, "lint", run)
        if any(token in lowered for token in ("e2e", "playwright", "cypress")):
            add_unique(commands, "e2e", run)
        if any(token in lowered for token in ("audit", "security", "sast", "semgrep", "trivy", "dependency-check")):
            add_unique(commands, "security", run)
    if runner == "npm" and ((path.parent / "package-lock.json").exists() or (path.parent / "npm-shrinkwrap.json").exists()):
        add_unique(commands, "security", f"{prefix}npm audit --audit-level=high")
    elif runner == "pnpm":
        add_unique(commands, "security", f"{prefix}pnpm audit --audit-level=high")
    elif runner == "yarn":
        add_unique(commands, "security", f"{prefix}yarn npm audit --severity high")
    web_packages = {
        "@angular/core",
        "@playwright/test",
        "@remix-run/react",
        "@sveltejs/kit",
        "astro",
        "cypress",
        "next",
        "playwright",
        "react",
        "svelte",
        "vite",
        "vue",
    }
    script_text = "\n".join(f"{name} {command}" for name, command in scripts.items()).lower()
    web_app = bool(web_packages.intersection(all_packages)) or any(
        token in script_text
        for token in (
            "astro",
            "cypress",
            "next ",
            "playwright",
            "react-scripts",
            "remix",
            "storybook",
            "svelte",
            "vite",
        )
    )
    playwright_available = "playwright" in all_packages or "@playwright/test" in all_packages or "playwright" in script_text
    web_review = None
    if web_app:
        e2e_commands = commands.get("e2e", [])
        web_review = {
            "path": relative(path, root),
            "runner": runner,
            "playwright_available": playwright_available,
            "e2e_commands": e2e_commands,
            "required_evidence": [
                "backend/frontend services and repository E2E command when both surfaces exist",
                "Playwright visual screenshot or toHaveScreenshot evidence for changed UI at desktop and one mobile viewport when practical",
                "DOM locator assertions using data-testid, role, or label selectors instead of brittle CSS/XPath selectors",
                "ARIA snapshot or accessibility-tree evidence for changed interactive surfaces when practical",
                "console error/warn and failed network request collection during the target flow",
            ],
            "missing_contracts": [],
        }
        if not e2e_commands:
            web_review["missing_contracts"].append("no package script exposing Playwright/Cypress E2E was detected")
        if not playwright_available:
            web_review["missing_contracts"].append("no Playwright package or script was detected for visual and DOM review")
    return {
        "path": relative(path, root),
        "runner": runner,
        "engines": data.get("engines") or {},
        "commands": commands,
        "web_app_review": web_review,
    }


def discover_pyproject(path: Path, root: Path) -> dict[str, Any]:
    """Discover Python project contracts."""
    data = tomllib.loads(read_text(path))
    project = data.get("project") or {}
    tool = data.get("tool") or {}
    prefix = prefix_for(path, root)
    commands: dict[str, list[str]] = {}
    if (path.parent / "tests").exists():
        add_unique(commands, "test", f"{prefix}python3 -m pytest tests")
        add_unique(commands, "coverage", f"{prefix}python3 -m coverage run -m pytest tests && python3 -m coverage report --show-missing --fail-under=100")
    if "ruff" in tool:
        add_unique(commands, "lint", f"{prefix}python3 -m ruff check .")
    if "black" in tool:
        add_unique(commands, "lint", f"{prefix}python3 -m black --check .")
    if "mypy" in tool:
        add_unique(commands, "lint", f"{prefix}python3 -m mypy .")
    if "interrogate" in tool:
        add_unique(commands, "docstring", f"{prefix}python3 -m interrogate --fail-under=100 --verbose .")
    add_unique(commands, "security", f"{prefix}python3 -m pip_audit")
    add_unique(commands, "security", f"{prefix}python3 -m bandit -r .")
    return {"path": relative(path, root), "requires_python": project.get("requires-python", ""), "commands": commands}


def discover_workflow_versions(root: Path) -> dict[str, list[str]]:
    """Discover runtime versions from GitHub Actions matrix snippets."""
    versions: dict[str, list[str]] = {}
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.exists():
        return versions
    for path in sorted(workflow_dir.glob("*.y*ml")):
        text = read_text(path)
        for match in MATRIX_RE.finditer(text):
            language = match.group(1)
            for value in match.group(2).split(","):
                cleaned = value.strip().strip("\"'")
                add_unique(versions, language, f"{relative(path, root)}:{cleaned}")
        for match in VERSION_RE.finditer(text):
            add_unique(versions, match.group(1), f"{relative(path, root)}:{match.group(2).strip()}")
    return versions


def discover_version_files(root: Path) -> dict[str, list[str]]:
    """Discover common runtime version files."""
    files = {
        ".java-version": "java",
        ".node-version": "node",
        ".nvmrc": "node",
        ".python-version": "python",
        ".ruby-version": "ruby",
        ".tool-versions": "tool-versions",
        "rust-toolchain": "rust",
        "rust-toolchain.toml": "rust",
    }
    versions: dict[str, list[str]] = {}
    for file_name, language in files.items():
        path = root / file_name
        if path.exists():
            add_unique(versions, language, f"{file_name}:{read_text(path).strip()}")
    go_mod = root / "go.mod"
    if go_mod.exists():
        for line in read_text(go_mod).splitlines():
            if line.startswith("go "):
                add_unique(versions, "go", f"go.mod:{line.split(None, 1)[1]}")
    return versions


def discover_unpackaged_surfaces(root: Path) -> list[dict[str, Any]]:
    """Find source files without a nearby package/test manifest."""
    findings: list[dict[str, Any]] = []
    for language, config in LANGUAGE_SURFACES.items():
        files: list[str] = []
        for extension in config["extensions"]:
            files.extend(relative(path, root) for path in root.rglob(f"*{extension}") if not any(part in {".git", "node_modules", ".venv", "venv"} for part in path.parts))
        if not files:
            continue
        has_manifest = any(any(root.glob(pattern)) for pattern in config["manifests"])
        if not has_manifest:
            findings.append(
                {
                    "language": language,
                    "sample_files": sorted(files)[:20],
                    "problem": "source files exist but no package/test manifest was detected",
                    "recommendation": f"add a package, build, test, coverage, and lint contract for {language} or document why these files are not executable source",
                }
            )
    return findings


def discover_contracts(repo_root: Path) -> dict[str, Any]:
    """Discover test, coverage, lint, security, and package contracts."""
    root = repo_root.resolve()
    contracts: dict[str, Any] = {
        "docker": [],
        "coverage_commands": [],
        "docstring_commands": [],
        "e2e_commands": [],
        "go": [],
        "java": [],
        "lint_commands": [],
        "node": [],
        "python": [],
        "r": [],
        "runtime_versions": discover_version_files(root),
        "rust": [],
        "security_commands": [],
        "test_commands": [],
        "unpackaged_source_surfaces": discover_unpackaged_surfaces(root),
        "web_app_review_requirements": [],
        "workflow_versions": discover_workflow_versions(root),
    }
    for path in sorted(root.rglob("package.json")):
        if "node_modules" not in path.parts:
            contract = discover_package_json(path, root)
            contracts["node"].append(contract)
            add_command_indexes(contracts, contract["commands"])
            if contract["web_app_review"]:
                contracts["web_app_review_requirements"].append(contract["web_app_review"])
    for path in sorted(root.rglob("pyproject.toml")):
        if not any(part in {".venv", "venv"} for part in path.parts):
            contract = discover_pyproject(path, root)
            contracts["python"].append(contract)
            add_command_indexes(contracts, contract["commands"])
    for path in sorted(root.rglob("Cargo.toml")):
        commands = {
            "test": ["cargo test --workspace --all-features"],
            "coverage": ["cargo llvm-cov --workspace --all-features --fail-under-lines 100 --show-missing-lines"],
            "lint": ["cargo clippy --workspace --all-targets --all-features -- -D warnings"],
            "security": ["cargo audit"],
        }
        contracts["rust"].append({"path": relative(path, root), "commands": commands})
        add_command_indexes(contracts, commands)
    for path in sorted(root.rglob("go.mod")):
        prefix = prefix_for(path, root)
        commands = {
            "test": [f"{prefix}go test ./..."],
            "lint": [f"{prefix}go vet ./...", f"{prefix}golangci-lint run"],
            "security": [f"{prefix}gosec ./...", f"{prefix}govulncheck ./..."],
        }
        contracts["go"].append({"path": relative(path, root), "commands": commands})
        add_command_indexes(contracts, commands)
    for path in sorted(root.rglob("pom.xml")) + sorted(root.rglob("build.gradle")) + sorted(root.rglob("build.gradle.kts")):
        prefix = prefix_for(path, root)
        if path.name == "pom.xml":
            commands = {"test": [f"{prefix}mvn test"], "lint": [f"{prefix}mvn verify"], "security": [f"{prefix}trivy fs ."]}
        else:
            runner = "./gradlew" if (path.parent / "gradlew").exists() else "gradle"
            commands = {"test": [f"{prefix}{runner} test"], "lint": [f"{prefix}{runner} check"], "security": [f"{prefix}trivy fs ."]}
        contracts["java"].append({"path": relative(path, root), "commands": commands})
        add_command_indexes(contracts, commands)
    for path in sorted(root.rglob("DESCRIPTION")):
        prefix = prefix_for(path, root)
        commands = {
            "test": [f"{prefix}Rscript -e 'testthat::test_dir(\"tests/testthat\")'"],
            "coverage": [f"{prefix}Rscript -e 'covr::package_coverage()'"],
            "lint": [f"{prefix}Rscript -e 'lintr::lint_package()'"],
        }
        contracts["r"].append({"path": relative(path, root), "commands": commands})
        add_command_indexes(contracts, commands)
    for pattern in ("Dockerfile", "*/Dockerfile", "Dockerfile.*", "*/Dockerfile.*", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                contracts["docker"].append(relative(path, root))
    if contracts["docker"]:
        contracts["lint_commands"].append("hadolint Dockerfile")
        contracts["security_commands"].append("trivy fs .")
    return contracts


def render_markdown(contracts: dict[str, Any]) -> str:
    """Render contracts as Markdown for review evidence."""
    lines = ["# Review Execution Contracts", ""]
    for key in (
        "runtime_versions",
        "workflow_versions",
        "unpackaged_source_surfaces",
        "test_commands",
        "coverage_commands",
        "docstring_commands",
        "e2e_commands",
        "lint_commands",
        "security_commands",
        "web_app_review_requirements",
    ):
        lines.extend([f"## {key}", "```json", json.dumps(contracts[key], ensure_ascii=False, indent=2, sort_keys=True), "```", ""])
    for key in ("python", "node", "rust", "go", "java", "r", "docker"):
        lines.extend([f"## {key}", "```json", json.dumps(contracts[key], ensure_ascii=False, indent=2, sort_keys=True), "```", ""])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run contract discovery."""
    args = parse_args(argv)
    contracts = discover_contracts(Path(args.repo_root))
    if args.format == "markdown":
        print(render_markdown(contracts))
    else:
        print(json.dumps(contracts, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
