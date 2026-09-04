"""Reconcile public GitHub repository metadata from a reviewed desired-state manifest.

The reconciler is intentionally narrow: it changes repository descriptions,
repository topics, and GitHub Pages settings. README content remains owned by
the target repository so badge/content changes can pass through that
repository's normal review path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ORGANIZATION = "ContextualWisdomLab"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
MAX_DESCRIPTION_CHARS = 350
PAGES_BASE_URL = f"https://{ORGANIZATION.casefold()}.github.io"
PAGES_MODES = {"legacy", "workflow"}


class ManifestError(ValueError):
    """Raised when desired repository metadata is malformed or unsafe."""


class _NoPagesRedirects(HTTPRedirectHandler):
    """Refuse redirects so Pages verification cannot be redirected off GitHub Pages."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Raise an HTTPError instead of following the redirect."""

        from urllib.error import HTTPError

        raise HTTPError(req.full_url, code, msg, headers, fp)


def _require_exact_dict(value: Any, *, field: str) -> dict[str, Any]:
    """Return a plain dictionary or reject behavior-bearing mapping objects."""

    if type(value) is not dict:
        raise ManifestError(f"{field} must be an object")
    return value


def _validate_repository(name: str, raw: Any) -> dict[str, Any]:
    """Validate one repository desired-state record and return a safe snapshot."""

    if not isinstance(name, str) or not REPOSITORY_RE.fullmatch(name):
        raise ManifestError("repository names must preserve exact GitHub-safe casing")
    item = _require_exact_dict(raw, field=f"repositories.{name}")
    required = {"description", "topics", "deepwiki", "pages"}
    allowed = required | {"pages_mode"}
    if not required.issubset(item) or not set(item).issubset(allowed):
        raise ManifestError(
            f"repositories.{name} must contain exactly {sorted(required)} plus optional pages_mode"
        )

    description = item["description"]
    if (
        type(description) is not str
        or not description.strip()
        or len(description) > MAX_DESCRIPTION_CHARS
    ):
        raise ManifestError(f"repositories.{name}.description is invalid")
    lowered = description.lower()
    if (
        "do not " in lowered
        or "#" in description
        or "http://" in lowered
        or "https://" in lowered
    ):
        raise ManifestError(
            f"repositories.{name}.description contains internal-facing or navigational text"
        )

    topics = item["topics"]
    if type(topics) is not list or not 1 <= len(topics) <= 20:
        raise ManifestError(f"repositories.{name}.topics must contain 1..20 topics")
    if any(
        type(topic) is not str or not TOPIC_RE.fullmatch(topic) for topic in topics
    ):
        raise ManifestError(f"repositories.{name}.topics contains an invalid topic")
    if len(set(topics)) != len(topics):
        raise ManifestError(f"repositories.{name}.topics contains duplicates")

    if type(item["deepwiki"]) is not bool or type(item["pages"]) is not bool:
        raise ManifestError(
            f"repositories.{name} deepwiki/pages flags must be booleans"
        )
    pages_mode = item.get("pages_mode", "legacy")
    if type(pages_mode) is not str or pages_mode not in PAGES_MODES:
        raise ManifestError(
            f"repositories.{name}.pages_mode must be one of {sorted(PAGES_MODES)}"
        )
    if not item["pages"] and "pages_mode" in item:
        raise ManifestError(
            f"repositories.{name}.pages_mode is only valid when Pages is enabled"
        )

    validated = {
        "description": description,
        "topics": list(topics),
        "deepwiki": item["deepwiki"],
        "pages": item["pages"],
    }
    if "pages_mode" in item:
        validated["pages_mode"] = pages_mode
    return validated


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Load and validate the complete desired-state manifest."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    root = _require_exact_dict(payload, field="manifest")
    if set(root) != {"schema_version", "organization", "repositories"}:
        raise ManifestError("manifest has an unexpected key set")
    if (
        type(root["schema_version"]) is not int
        or root["schema_version"] != 1
        or root["organization"] != ORGANIZATION
    ):
        raise ManifestError("manifest schema or organization is unsupported")
    repositories = _require_exact_dict(root["repositories"], field="repositories")
    if not repositories:
        raise ManifestError("manifest must declare at least one repository")

    validated: dict[str, dict[str, Any]] = {}
    casing_by_identity: dict[str, str] = {}
    for name, value in repositories.items():
        state = _validate_repository(name, value)
        identity = name.casefold()
        prior = casing_by_identity.get(identity)
        if prior is not None and prior != name:
            raise ManifestError(
                f"repository casing collision: {prior} and {name} identify the same GitHub repository"
            )
        casing_by_identity[identity] = name
        validated[name] = state
    return validated


def _gh_api(
    method: str,
    endpoint: str,
    *,
    fields: dict[str, Any] | None = None,
    body: Any = None,
) -> str:
    """Call GitHub CLI with fixed API endpoints and content-bounded arguments."""

    command = ["gh", "api", "--method", method, endpoint]
    if body is not None:
        command.extend(["--input", "-"])
    for key, value in (fields or {}).items():
        command.extend(["--field", f"{key}={value}"])
    completed = subprocess.run(
        command,
        check=False,
        input=None if body is None else json.dumps(body, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"GitHub API request failed for {endpoint}")
    return completed.stdout


def _pages_exists(repository: str) -> bool:
    """Return whether GitHub Pages already exists for the repository."""

    command = ["gh", "api", f"repos/{ORGANIZATION}/{repository}/pages"]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode == 0:
        return True
    combined = f"{completed.stdout}\n{completed.stderr}"
    if "HTTP 404" in combined or "Not Found" in combined:
        return False
    raise RuntimeError(f"GitHub Pages state could not be resolved for {repository}")


def _pages_configuration(repository: str) -> dict[str, Any]:
    """Return the current Pages configuration after existence has been established."""

    payload = json.loads(_gh_api("GET", f"repos/{ORGANIZATION}/{repository}/pages"))
    return _require_exact_dict(payload, field=f"Pages configuration for {repository}")


def _pages_configuration_matches(current: dict[str, Any], default_branch: str) -> bool:
    """Return whether Pages already serves the desired legacy /docs source."""

    source = current.get("source")
    if type(source) is not dict:
        return False
    return (
        source.get("branch") == default_branch
        and source.get("path") == "/docs"
        and current.get("build_type") in (None, "legacy")
    )


def _workflow_pages_configuration_matches(current: dict[str, Any]) -> bool:
    """Return whether Pages is explicitly owned by a GitHub Actions deployment."""

    return current.get("build_type") == "workflow"


def _pages_url_is_expected(url: Any) -> bool:
    """Return whether a URL is confined to the organization-owned Pages origin."""

    return type(url) is str and (
        url == PAGES_BASE_URL or url.startswith(f"{PAGES_BASE_URL}/")
    )


def _pages_publication_ready(repository: str, current: dict[str, Any]) -> None:
    """Require a built Pages site whose published HTTPS URL is actually reachable."""

    if current.get("status") != "built":
        raise RuntimeError(f"GitHub Pages is not built for {repository}")
    html_url = current.get("html_url")
    if not _pages_url_is_expected(html_url):
        raise RuntimeError(f"GitHub Pages URL is invalid for {repository}")
    request = Request(
        html_url,
        headers={"User-Agent": "ContextualWisdomLab-repository-metadata-reconcile"},
    )
    opener = build_opener(_NoPagesRedirects())
    try:
        with opener.open(request, timeout=10) as response:
            if not response.read(1):
                raise RuntimeError(f"GitHub Pages returned empty content for {repository}")
    except (URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, HTTPError):
            exc.close()
        raise RuntimeError(f"GitHub Pages is not reachable for {repository}") from exc


def _repository_file_exists(repository: str, default_branch: str, path: str) -> bool:
    """Return whether a reviewed default-branch regular file exists at the exact path."""

    endpoint = f"repos/{ORGANIZATION}/{repository}/contents/{path}?ref={default_branch}"
    command = ["gh", "api", endpoint]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode == 0:
        payload = json.loads(completed.stdout)
        return type(payload) is dict and payload.get("type") == "file"
    combined = f"{completed.stdout}\n{completed.stderr}"
    if "HTTP 404" in combined or "Not Found" in combined:
        return False
    raise RuntimeError(
        f"GitHub Pages source state could not be resolved for {repository}:{path}"
    )


def _docs_index_exists(repository: str, default_branch: str) -> bool:
    """Return whether the reviewed default branch contains docs/index.md."""

    return _repository_file_exists(repository, default_branch, "docs/index.md")


def _workflow_pages_definition_exists(repository: str, default_branch: str) -> bool:
    """Return whether the standard reviewed Pages workflow exists on the default branch."""

    return _repository_file_exists(
        repository, default_branch, ".github/workflows/pages.yml"
    )


def _deepwiki_badge_linked(readme: str, repository: str) -> bool:
    """Return whether one badge image links to the exact repository DeepWiki target."""

    image = re.escape("https://deepwiki.com/badge.svg")
    target = re.escape(f"https://deepwiki.com/{ORGANIZATION}/{repository}")
    markdown = re.compile(rf"\[!\[[^\]]*\]\({image}\)\]\({target}\)")
    html = re.compile(
        rf"<a\b(?:(?!>).)*\bhref=[\"'](?-i:{target})[\"'](?:(?!>).)*>"
        rf"(?:(?!</a\s*>).)*?"
        rf"<img\b(?:(?!>).)*\bsrc=[\"'](?-i:{image})[\"'](?:(?!>).)*>"
        rf"(?:(?!</a\s*>).)*?</a\s*>",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(markdown.search(readme) or html.search(readme))


def _deepwiki_badge_exists(repository: str, default_branch: str) -> bool:
    """Return whether the default-branch README carries the exact linked badge."""

    endpoint = f"repos/{ORGANIZATION}/{repository}/contents/README.md?ref={default_branch}"
    command = [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github.raw+json",
        endpoint,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        combined = f"{completed.stdout}\n{completed.stderr}"
        if "HTTP 404" in combined or "Not Found" in combined:
            return False
        raise RuntimeError(f"README state could not be resolved for {repository}")
    return _deepwiki_badge_linked(completed.stdout, repository)


def _pages_precondition(repository: str, default_branch: str, desired: dict[str, Any]) -> None:
    """Require the reviewed source contract for the selected Pages deployment mode."""

    if not desired["pages"]:
        return
    pages_mode = desired.get("pages_mode", "legacy")
    if pages_mode == "workflow":
        if not _workflow_pages_definition_exists(repository, default_branch):
            raise RuntimeError(
                f"workflow Pages requested for {repository} but .github/workflows/pages.yml is not on {default_branch}"
            )
        return
    if not _docs_index_exists(repository, default_branch):
        raise RuntimeError(
            f"Pages requested for {repository} but docs/index.md is not on {default_branch}"
        )


def _workflow_pages_live_precondition(repository: str, desired: dict[str, Any]) -> None:
    """Require existing Actions-backed Pages before any repository metadata mutation."""

    if not desired["pages"] or desired.get("pages_mode", "legacy") != "workflow":
        return
    if not _pages_exists(repository):
        raise RuntimeError(
            f"workflow Pages requested for {repository} but Pages is not configured"
        )
    current_pages = _pages_configuration(repository)
    if not _workflow_pages_configuration_matches(current_pages):
        raise RuntimeError(
            f"workflow Pages requested for {repository} but live Pages is not Actions-backed"
        )


def reconcile_repository(repository: str, desired: dict[str, Any]) -> None:
    """Apply one validated desired-state record through least-privilege GitHub APIs."""

    repository_payload = json.loads(
        _gh_api("GET", f"repos/{ORGANIZATION}/{repository}")
    )
    default_branch = repository_payload.get("default_branch")
    if type(default_branch) is not str or not default_branch:
        raise RuntimeError(f"default branch could not be resolved for {repository}")

    badge_exists = _deepwiki_badge_exists(repository, default_branch)
    if desired["deepwiki"] and not badge_exists:
        raise RuntimeError(
            f"DeepWiki badge requested for {repository} but the exact badge is not on {default_branch}"
        )
    if not desired["deepwiki"] and badge_exists:
        raise RuntimeError(
            f"DeepWiki badge is disabled for {repository} but the exact badge is still on {default_branch}"
        )
    _pages_precondition(repository, default_branch, desired)
    _workflow_pages_live_precondition(repository, desired)

    if repository_payload.get("description") != desired["description"]:
        _gh_api(
            "PATCH",
            f"repos/{ORGANIZATION}/{repository}",
            body={"description": desired["description"]},
        )

    current_topics = json.loads(
        _gh_api("GET", f"repos/{ORGANIZATION}/{repository}/topics")
    ).get("names", [])
    if set(current_topics) != set(desired["topics"]):
        _gh_api(
            "PUT",
            f"repos/{ORGANIZATION}/{repository}/topics",
            body={"names": desired["topics"]},
        )

    pages_mode = desired.get("pages_mode", "legacy")
    if desired["pages"] and pages_mode == "workflow":
        return

    pages_exists = _pages_exists(repository)
    if desired["pages"]:
        pages_body = {
            "build_type": "legacy",
            "source": {"branch": default_branch, "path": "/docs"},
        }
        if not pages_exists:
            _gh_api(
                "POST",
                f"repos/{ORGANIZATION}/{repository}/pages",
                body=pages_body,
            )
        elif not _pages_configuration_matches(
            _pages_configuration(repository), default_branch
        ):
            _gh_api(
                "PUT",
                f"repos/{ORGANIZATION}/{repository}/pages",
                body=pages_body,
            )
    elif pages_exists:
        _gh_api("DELETE", f"repos/{ORGANIZATION}/{repository}/pages")


def verify_repository(repository: str, desired: dict[str, Any]) -> None:
    """Re-read live public state and fail unless it exactly matches desired state."""

    repository_payload = json.loads(
        _gh_api("GET", f"repos/{ORGANIZATION}/{repository}")
    )
    default_branch = repository_payload.get("default_branch")
    if type(default_branch) is not str or not default_branch:
        raise RuntimeError(f"default branch could not be resolved for {repository}")
    if repository_payload.get("description") != desired["description"]:
        raise RuntimeError(f"description did not converge for {repository}")

    current_topics = json.loads(
        _gh_api("GET", f"repos/{ORGANIZATION}/{repository}/topics")
    ).get("names", [])
    if set(current_topics) != set(desired["topics"]):
        raise RuntimeError(f"topics did not converge for {repository}")

    badge_exists = _deepwiki_badge_exists(repository, default_branch)
    if badge_exists != desired["deepwiki"]:
        raise RuntimeError(f"DeepWiki state did not converge for {repository}")
    if desired["pages"]:
        pages_mode = desired.get("pages_mode", "legacy")
        if pages_mode == "workflow":
            if not _workflow_pages_definition_exists(repository, default_branch):
                raise RuntimeError(
                    f"Pages workflow source did not converge for {repository}"
                )
        elif not _docs_index_exists(repository, default_branch):
            raise RuntimeError(f"Pages source did not converge for {repository}")

    pages_exists = _pages_exists(repository)
    if desired["pages"]:
        if not pages_exists:
            raise RuntimeError(f"GitHub Pages was not published for {repository}")
        current_pages = _pages_configuration(repository)
        pages_mode = desired.get("pages_mode", "legacy")
        if pages_mode == "workflow":
            if not _workflow_pages_configuration_matches(current_pages):
                raise RuntimeError(
                    f"GitHub Pages deployment mode did not converge for {repository}"
                )
        elif not _pages_configuration_matches(current_pages, default_branch):
            raise RuntimeError(f"GitHub Pages configuration did not converge for {repository}")
        _pages_publication_ready(repository, current_pages)
    elif pages_exists:
        raise RuntimeError(f"GitHub Pages remained published for {repository}")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for validation, apply, or verification mode."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--repository", action="append", default=[])
    return parser.parse_args()


def _select_repositories(
    requested: list[str], repositories: dict[str, dict[str, Any]]
) -> list[str]:
    """Canonicalize case-insensitive GitHub identities to reviewed repository casing."""

    if not requested:
        return list(repositories)
    canonical_by_identity = {name.casefold(): name for name in repositories}
    selected: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []
    for candidate in requested:
        identity = candidate.casefold()
        canonical = canonical_by_identity.get(identity)
        if canonical is None:
            unknown.append(candidate)
            continue
        if identity not in seen:
            seen.add(identity)
            selected.append(canonical)
    if unknown:
        raise ManifestError(f"undeclared repositories requested: {', '.join(sorted(unknown))}")
    return selected


def main() -> int:
    """Validate, reconcile, or verify every independent repository possible."""

    args = parse_args()
    repositories = load_manifest(args.manifest)
    if args.validate_only:
        return 0
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("GH_TOKEN is required outside validation mode")
    selected = _select_repositories(args.repository, repositories)
    operation = verify_repository if getattr(args, "verify_only", False) else reconcile_repository

    failures: list[str] = []
    for repository in selected:
        try:
            operation(repository, repositories[repository])
        except (
            ManifestError,
            RuntimeError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ) as exc:
            failures.append(f"{repository}: {exc}")
            print(
                f"repository metadata reconciliation failed for {repository}: {exc}",
                file=sys.stderr,
            )
    if failures:
        raise RuntimeError("metadata reconciliation failed: " + "; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
