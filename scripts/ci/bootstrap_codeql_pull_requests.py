#!/usr/bin/env python3
"""Create one idempotent OpenCode-owned CodeQL setup PR for uncovered repositories."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, TextIO

from scripts.ci.audit_org_codeql_coverage import repositories_without_codeql


ORGANIZATION = "ContextualWisdomLab"
BOOTSTRAP_BRANCH = "opencode/codeql-setup"
WORKFLOW_PATH = ".github/workflows/codeql.yml"


class GitHubError(RuntimeError):
    """Report a bounded GitHub API or repository-state failure."""


class GitHubClient:
    """Use the GitHub CLI with an OpenCode installation token."""

    def __init__(self, token: str, *, timeout_seconds: int = 60) -> None:
        """Store a non-empty opaque token without format or length assumptions."""
        if not token:
            raise GitHubError("OPENCODE_APP_TOKEN is required")
        self._token = token
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> GitHubClient:
        """Build a client from the explicit OpenCode installation token."""
        values = os.environ if environ is None else environ
        return cls(str(values.get("OPENCODE_APP_TOKEN") or "").strip())

    def request(self, path: str, *, method: str = "GET", payload: Any = None) -> Any:
        """Call one REST endpoint and decode its JSON response."""
        args = ["gh", "api", path]
        if method != "GET":
            args.extend(["--method", method])
        input_text = None
        if payload is not None:
            args.extend(["--input", "-"])
            input_text = json.dumps(payload, separators=(",", ":"))
        try:
            result = subprocess.run(
                args,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env={**os.environ, "GH_TOKEN": self._token},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError(f"GitHub API transport failed: {type(exc).__name__}") from exc
        if result.returncode:
            diagnostic = (result.stderr or result.stdout or "request failed")[-600:]
            diagnostic = diagnostic.replace(self._token, "[REDACTED]")
            raise GitHubError(f"GitHub API {method} {path} failed: {diagnostic}")
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GitHub API returned invalid JSON for {path}") from exc


def render_workflow(default_branch: str) -> str:
    """Render a no-autobuild CodeQL workflow that redetects stacks on every run."""
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", default_branch) or ".." in default_branch:
        raise ValueError("default branch is not safe for workflow generation")
    return f'''name: CodeQL

on:
  pull_request:
  push:
    branches: [{json.dumps(default_branch)}]
  schedule:
    - cron: "23 4 * * 3"

concurrency:
  group: codeql-${{{{ github.repository }}}}-${{{{ github.event.pull_request.number || github.ref }}}}
  cancel-in-progress: true

permissions:
  contents: read
  security-events: write

jobs:
  detect-languages:
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{{{ steps.detect.outputs.matrix }}}}
    steps:
      - id: detect
        env:
          GH_TOKEN: ${{{{ github.token }}}}
        run: |
          set -euo pipefail
          languages="$(gh api "repos/${{{{ github.repository }}}}/languages")"
          jq -cn --argjson languages "$languages" '{{
            include: ([{{language:"actions","build-mode":"none"}}] + [
              ($languages | keys[]) as $name |
              {{
                language: ({{
                  "C":"c-cpp","C++":"c-cpp","C#":"csharp","Go":"go",
                  "Java":"java-kotlin","Kotlin":"java-kotlin",
                  "JavaScript":"javascript-typescript","TypeScript":"javascript-typescript",
                  "Python":"python","Ruby":"ruby","Rust":"rust","Swift":"swift"
                }}[$name]),
                "build-mode":"none"
              }} | select(.language != null)
            ] | unique_by(.language))
          }}' > matrix.json
          echo "matrix=$(cat matrix.json)" >> "$GITHUB_OUTPUT"

  analyze:
    name: Analyze (${{{{ matrix.language }}}})
    needs: detect-languages
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix: ${{{{ fromJSON(needs.detect-languages.outputs.matrix) }}}}
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - uses: github/codeql-action/init@cdf488f595d80d6e07e03d4674febd5ab45fa938 # v4.37.9
        with:
          languages: ${{{{ matrix.language }}}}
          build-mode: ${{{{ matrix.build-mode }}}}
      - uses: github/codeql-action/analyze@cdf488f595d80d6e07e03d4674febd5ab45fa938 # v4.37.9
'''


def bootstrap_repository(client: GitHubClient, repository: str) -> str:
    """Create the setup branch, workflow commit, and PR, or return a skip reason."""
    full_name = f"{ORGANIZATION}/{repository}"
    metadata = client.request(f"repos/{full_name}") or {}
    default_branch = str(metadata.get("default_branch") or "")
    if not default_branch:
        return "pending-empty-repository"
    base = client.request(f"repos/{full_name}/git/ref/heads/{default_branch}") or {}
    base_sha = str(((base.get("object") or {}).get("sha")) or "")
    if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
        raise GitHubError(f"{full_name} returned an invalid default-branch SHA")

    existing = client.request(
        f"repos/{full_name}/pulls?state=open&head={ORGANIZATION}:{BOOTSTRAP_BRANCH}"
    ) or []
    if existing:
        return "open-pr-exists"
    try:
        client.request(f"repos/{full_name}/git/ref/heads/{BOOTSTRAP_BRANCH}")
    except GitHubError as exc:
        if "HTTP 404" not in str(exc):
            raise
    else:
        raise GitHubError(f"{full_name} has an unmanaged {BOOTSTRAP_BRANCH} branch")

    client.request(
        f"repos/{full_name}/git/refs",
        method="POST",
        payload={"ref": f"refs/heads/{BOOTSTRAP_BRANCH}", "sha": base_sha},
    )
    content = render_workflow(default_branch)
    client.request(
        f"repos/{full_name}/contents/{WORKFLOW_PATH}",
        method="PUT",
        payload={
            "message": "ci(codeql): add adaptive CodeQL analysis",
            "content": base64.b64encode(content.encode()).decode(),
            "branch": BOOTSTRAP_BRANCH,
        },
    )
    pull = client.request(
        f"repos/{full_name}/pulls",
        method="POST",
        payload={
            "title": "ci(codeql): add adaptive CodeQL analysis",
            "head": BOOTSTRAP_BRANCH,
            "base": default_branch,
            "body": (
                "OpenCode Agent detected that this repository has no active CodeQL coverage. "
                "This SHA-pinned workflow redetects supported languages on every run and never "
                "executes repository build scripts."
            ),
        },
    ) or {}
    return f"created-pr-{pull.get('number', 'unknown')}"


def load_payload(path: Path, stdin: TextIO) -> list[dict[str, Any]]:
    """Load and validate the shared coverage payload."""
    if path == Path("-"):
        payload = json.load(stdin)
    else:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("repository JSON root must be a list")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the coverage payload path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories_json", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Bootstrap every uncovered repository and fail closed on any write failure."""
    args = parse_args(argv)
    try:
        repositories = load_payload(args.repositories_json, sys.stdin)
        client = GitHubClient.from_environment()
        for repository in repositories_without_codeql(repositories):
            name = str(repository.get("name") or "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise GitHubError("coverage payload contained an invalid repository name")
            print(f"CODEQL_BOOTSTRAP repository={name} result={bootstrap_repository(client, name)}")
    except (OSError, ValueError, json.JSONDecodeError, GitHubError) as exc:
        print(f"ERROR: CodeQL bootstrap failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
