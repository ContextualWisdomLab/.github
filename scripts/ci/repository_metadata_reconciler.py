"""Reconcile ContextualWisdomLab repository-facing metadata from declarative state."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_VERSION = "2026-03-10"
DESCRIPTION_MAX = 350
TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")
ISSUE_REF_RE = re.compile(r"(?:^|\s)#\d+\b")
INTERNAL_DESCRIPTION_RE = re.compile(
    r"\b(?:do not|must not|internal only|migration warning|owned by issue|owned by pr)\b",
    re.IGNORECASE,
)


def deepwiki_markdown(organization: str, repository: str) -> str:
    """Return the canonical Ask DeepWiki badge for one exact repository name."""
    return (
        "[![Ask DeepWiki](https://deepwiki.com/badge.svg)]"
        f"(https://deepwiki.com/{organization}/{repository})"
    )


def _validate_description(description: object) -> str:
    """Validate one customer-facing repository description."""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")
    if len(description) > DESCRIPTION_MAX or "\n" in description:
        raise ValueError("description must fit the GitHub customer-facing field")
    if ISSUE_REF_RE.search(description) or INTERNAL_DESCRIPTION_RE.search(description):
        raise ValueError("customer-facing description contains internal instructions or issue references")
    return description


def _validate_topics(topics: object) -> list[str]:
    """Validate normalized GitHub topic slugs without silently rewriting them."""
    if not isinstance(topics, list) or not topics:
        raise ValueError("topic list must be non-empty")
    if len(topics) > 20:
        raise ValueError("topic list exceeds GitHub's bounded repository taxonomy")
    if any(not isinstance(topic, str) or TOPIC_RE.fullmatch(topic) is None for topic in topics):
        raise ValueError("topic values must be normalized lowercase slugs")
    if len(set(topics)) != len(topics):
        raise ValueError("duplicate topic values are forbidden")
    return list(topics)


def _validate_pages(pages: object) -> dict[str, Any]:
    """Validate optional Pages intent and its only accepted source locations."""
    if not isinstance(pages, dict) or not isinstance(pages.get("enabled"), bool):
        raise ValueError("Pages intent must declare boolean enabled")
    if not pages["enabled"]:
        return {"enabled": False}
    source = pages.get("source")
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("branch"), str)
        or not source["branch"]
        or source.get("path") not in {"/", "/docs"}
    ):
        raise ValueError("Pages enabled state requires a branch and / or /docs source")
    return {"enabled": True, "source": {"branch": source["branch"], "path": source["path"]}}


def validate_manifest(raw: object) -> dict[str, Any]:
    """Validate the desired-state manifest without inventing missing metadata."""
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("schema_version must equal 1")
    if raw.get("organization") != "ContextualWisdomLab":
        raise ValueError("organization must preserve exact ContextualWisdomLab casing")
    repositories = raw.get("repositories")
    if not isinstance(repositories, dict) or not repositories:
        raise ValueError("repositories must be a non-empty object")
    validated: dict[str, dict[str, Any]] = {}
    for repository, desired in repositories.items():
        if not isinstance(repository, str) or "/" in repository or repository.strip() != repository:
            raise ValueError("repository names must be exact unqualified names")
        if not isinstance(desired, dict):
            raise ValueError(f"{repository}: desired state must be an object")
        deepwiki = desired.get("deepwiki")
        if not isinstance(deepwiki, bool):
            raise ValueError(f"{repository}: deepwiki must be boolean")
        validated[repository] = {
            "description": _validate_description(desired.get("description")),
            "topics": _validate_topics(desired.get("topics")),
            "deepwiki": deepwiki,
            "pages": _validate_pages(desired.get("pages", {"enabled": False})),
        }
        if "homepage" in desired:
            homepage = desired["homepage"]
            if homepage is not None and not isinstance(homepage, str):
                raise ValueError(f"{repository}: homepage must be a string or null")
            validated[repository]["homepage"] = homepage
    return {
        "schema_version": 1,
        "organization": "ContextualWisdomLab",
        "repositories": validated,
    }


def plan_operations(repository: str, live: dict[str, Any], desired: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return the minimal ordered REST mutations needed for one repository."""
    del repository
    operations: list[tuple[str, dict[str, Any]]] = []
    repository_patch: dict[str, Any] = {}
    if live.get("description") != desired["description"]:
        repository_patch["description"] = desired["description"]
    if "homepage" in desired and live.get("homepage") != desired["homepage"]:
        repository_patch["homepage"] = desired["homepage"]
    if repository_patch:
        operations.append(("repository", repository_patch))
    if live.get("topics", []) != desired["topics"]:
        operations.append(("topics", {"names": desired["topics"]}))
    pages = desired["pages"]
    if pages["enabled"]:
        payload = {"build_type": "legacy", "source": pages["source"]}
        if not live.get("has_pages"):
            operations.append(("pages_create", payload))
        else:
            current_pages = live.get("pages", {})
            if (
                current_pages.get("build_type") != "legacy"
                or current_pages.get("source") != pages["source"]
            ):
                operations.append(("pages_update", payload))
    return operations


class GitHubApi:
    """Minimal GitHub REST client for repository administration metadata."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        allow_status: tuple[int, ...] = (),
    ) -> Any:
        """Perform one bounded JSON REST request and optionally admit known status codes."""
        url = f"https://api.github.com{path}"
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "ContextualWisdomLab-repository-metadata-reconciler",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                if not body:
                    return {}
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code in allow_status:
                return None
            raise RuntimeError(f"GitHub API {method} {path} failed with HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RuntimeError(f"GitHub API {method} {path} transport failure") from error


def fetch_live_state(api: Any, organization: str, repository: str) -> dict[str, Any]:
    """Read repository metadata, topics, and Pages without promoting absent Pages."""
    base = f"/repos/{organization}/{repository}"
    repository_state = api.request("GET", base)
    topics_state = api.request("GET", f"{base}/topics")
    pages_state = api.request("GET", f"{base}/pages", allow_status=(404,))
    live = {
        "description": repository_state.get("description"),
        "homepage": repository_state.get("homepage"),
        "has_pages": bool(repository_state.get("has_pages")),
        "topics": topics_state.get("names", []),
    }
    if pages_state is not None:
        live["pages"] = pages_state
        live["has_pages"] = True
    return live


def apply_operations(
    api: Any,
    organization: str,
    repository: str,
    operations: list[tuple[str, dict[str, Any]]],
) -> None:
    """Apply planned operations using the exact GitHub REST authority endpoint."""
    base = f"/repos/{organization}/{repository}"
    for operation, payload in operations:
        if operation == "repository":
            api.request("PATCH", base, payload)
        elif operation == "topics":
            api.request("PUT", f"{base}/topics", payload)
        elif operation == "pages_create":
            api.request("POST", f"{base}/pages", payload)
        elif operation == "pages_update":
            api.request("PUT", f"{base}/pages", payload)
        else:
            raise ValueError(f"unknown operation: {operation}")


def _load_manifest(path: Path) -> dict[str, Any]:
    """Read and validate one UTF-8 JSON desired-state manifest."""
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    """Audit or apply the repository metadata desired state."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("audit", "apply"), default="audit")
    arguments = parser.parse_args(argv)
    manifest = _load_manifest(arguments.manifest)
    token = os.environ.get("CWL_REPOSITORY_METADATA_TOKEN")
    if arguments.mode == "apply" and not token:
        raise RuntimeError(
            "CWL_REPOSITORY_METADATA_TOKEN is required for Administration/Pages write authority"
        )
    api = GitHubApi(token)
    for repository, desired in manifest["repositories"].items():
        live = fetch_live_state(api, manifest["organization"], repository)
        operations = plan_operations(repository, live, desired)
        print(f"{repository}: {json.dumps(operations, sort_keys=True)}")
        if arguments.mode == "apply" and operations:
            apply_operations(api, manifest["organization"], repository, operations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
