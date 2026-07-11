import json
import runpy
import sys

from scripts.ci import review_execution_contracts as contracts


def test_discovers_runtime_lint_security_and_unpackaged_sources(tmp_path, capsys):
    """Contract discovery finds runtime matrices, linters, security tools, and package gaps."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text(
        "strategy:\n  matrix:\n    python-version: ['3.11', '3.12']\n    node-version: [20, 22]\n",
        encoding="utf-8",
    )
    (repo / ".nvmrc").write_text("22\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps(
            {
                "engines": {"node": ">=20"},
                "dependencies": {"react": "^19.0.0"},
                "devDependencies": {"@playwright/test": "^1.50.0"},
                "scripts": {
                    "coverage": "vitest run --coverage",
                    "e2e": "playwright test",
                    "lint": "eslint .",
                    "security": "semgrep scan",
                    "test": "vitest run",
                },
            }
        ),
        encoding="utf-8",
    )
    (repo / "package-lock.json").write_text("{}", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nrequires-python = '>=3.11'\n[tool.ruff]\n[tool.black]\n[tool.mypy]\n[tool.interrogate]\nfail-under = 100\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n", encoding="utf-8")
    (repo / "go.mod").write_text("module example.test/x\ngo 1.23\n", encoding="utf-8")
    (repo / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (repo / "loose.rb").write_text("puts 'unpackaged'\n", encoding="utf-8")

    result = contracts.discover_contracts(repo)

    assert result["runtime_versions"]["node"] == [".nvmrc:22"]
    assert ".github/workflows/ci.yml:3.11" in result["workflow_versions"]["python"]
    assert result["python"][0]["requires_python"] == ">=3.11"
    assert "npm run test" in result["test_commands"]
    assert "npm run coverage" in result["coverage_commands"]
    assert "npm run e2e" in result["e2e_commands"]
    assert result["web_app_review_requirements"][0]["playwright_available"] is True
    assert "npm run e2e" in result["web_app_review_requirements"][0]["e2e_commands"]
    assert any(
        "Playwright visual screenshot" in item
        for item in result["web_app_review_requirements"][0]["required_evidence"]
    )
    assert any("interrogate" in command for command in result["docstring_commands"])
    assert "npm run lint" in result["lint_commands"]
    assert any("ruff" in command for command in result["lint_commands"])
    assert any("black" in command for command in result["lint_commands"])
    assert any("mypy" in command for command in result["lint_commands"])
    assert "cargo audit" in result["security_commands"]
    assert "gosec ./..." in result["security_commands"]
    assert any(surface["language"] == "ruby" for surface in result["unpackaged_source_surfaces"])

    assert contracts.main(["--repo-root", str(repo), "--format", "markdown"]) == 0
    assert "Review Execution Contracts" in capsys.readouterr().out


def test_discovers_package_managers_java_r_json_and_main(tmp_path, capsys, monkeypatch):
    """Contract discovery covers alternate package managers and language manifests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    assert contracts.discover_workflow_versions(repo) == {}

    pnpm_dir = repo / "web-pnpm"
    pnpm_dir.mkdir()
    (pnpm_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (pnpm_dir / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "security": "audit"}}),
        encoding="utf-8",
    )

    yarn_dir = repo / "web-yarn"
    yarn_dir.mkdir()
    (yarn_dir / "yarn.lock").write_text("", encoding="utf-8")
    (yarn_dir / "package.json").write_text(
        json.dumps({"scripts": {"test": "jest"}}),
        encoding="utf-8",
    )

    maven_dir = repo / "java-maven"
    maven_dir.mkdir()
    (maven_dir / "pom.xml").write_text("<project />\n", encoding="utf-8")

    gradle_dir = repo / "java-gradle"
    gradle_dir.mkdir()
    (gradle_dir / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (gradle_dir / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

    r_dir = repo / "r-package"
    r_dir.mkdir()
    (r_dir / "DESCRIPTION").write_text("Package: sample\n", encoding="utf-8")

    result = contracts.discover_contracts(repo)

    assert any(entry["runner"] == "pnpm" for entry in result["node"])
    assert any(entry["runner"] == "yarn" for entry in result["node"])
    assert any("pnpm audit" in command for command in result["security_commands"])
    assert any("yarn npm audit" in command for command in result["security_commands"])
    assert any("mvn test" in command for command in result["test_commands"])
    assert any("./gradlew test" in command for command in result["test_commands"])
    assert any("Rscript" in command for command in result["coverage_commands"])

    assert contracts.main(["--repo-root", str(repo), "--format", "json"]) == 0
    assert '"java"' in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["review_execution_contracts.py", "--repo-root", str(repo), "--format", "json"])
    try:
        runpy.run_module("scripts.ci.review_execution_contracts", run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
