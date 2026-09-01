#!/usr/bin/env python3
"""Reconcile reviewed GitHub ruleset governance with fail-closed verification.

The reconciler manages only the two rulesets declared in a reviewed manifest. It
preserves live conditions and non-governance rules while canonicalizing the
reviewed pull-request controls. GitHub does not provide conditional PUT/PATCH
semantics for this endpoint, so the second live read is a drift detector rather
than a compare-and-swap guarantee. Privileged mutation is additionally bound to
the exact protected-main revision, serialized owner-plane execution, and the
immutable ruleset-history surface. If history proves a hidden pre-PUT edit was
overwritten, the reconciler restores the newest displaced administrator state
before failing; recovery re-checks immutable history after every restore write.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_VERSION = "2026-03-10"
ORGANIZATION = "ContextualWisdomLab"
CONTROL_REPOSITORY = "ContextualWisdomLab/.github"
DESIRED_MERGE_METHODS = ["merge", "squash"]
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COLLISION_RECOVERY_LIMIT = 8


class RulesetGovernanceError(RuntimeError):
    """Raised when desired-state validation or live reconciliation is unsafe."""


@dataclass(frozen=True)
class RulesetTarget:
    """Describe one exact organization- or repository-owned ruleset."""

    scope: str
    owner: str
    repository: str | None
    ruleset_id: int
    name: str

    @property
    def endpoint(self) -> str:
        """Return the GitHub REST endpoint for this exact ruleset."""

        if self.scope == "organization":
            return f"orgs/{self.owner}/rulesets/{self.ruleset_id}"
        return f"repos/{self.owner}/{self.repository}/rulesets/{self.ruleset_id}"

    @property
    def history_endpoint(self) -> str:
        """Return the immutable history endpoint for this exact ruleset."""

        return f"{self.endpoint}/history"

    def history_version_endpoint(self, version_id: int) -> str:
        """Return one exact immutable ruleset-history version endpoint."""

        if type(version_id) is not int or version_id <= 0:
            raise RulesetGovernanceError("ruleset history version identity is malformed")
        return f"{self.history_endpoint}/{version_id}"

    @property
    def source(self) -> str:
        """Return the exact source identity GitHub must report for this ruleset."""

        if self.scope == "organization":
            return self.owner
        return f"{self.owner}/{self.repository}"

    @property
    def source_type(self) -> str:
        """Return GitHub's expected source type for this ruleset scope."""

        return "Organization" if self.scope == "organization" else "Repository"


def _plain_dict(value: Any, *, field: str) -> dict[str, Any]:
    """Return a plain dictionary or reject behavior-bearing mapping objects."""

    if type(value) is not dict:
        raise RulesetGovernanceError(f"{field} must be an object")
    return value


def _plain_list(value: Any, *, field: str) -> list[Any]:
    """Return a plain list or reject behavior-bearing sequence objects."""

    if type(value) is not list:
        raise RulesetGovernanceError(f"{field} must be an array")
    return value


def load_manifest(path: Path) -> tuple[RulesetTarget, ...]:
    """Load and strictly validate the reviewed ruleset target manifest."""

    root = _plain_dict(json.loads(path.read_text(encoding="utf-8")), field="manifest")
    if set(root) != {"schema_version", "organization", "targets"}:
        raise RulesetGovernanceError("manifest has an unexpected key set")
    if root["schema_version"] != 1 or root["organization"] != ORGANIZATION:
        raise RulesetGovernanceError("manifest schema or organization is unsupported")

    raw_targets = _plain_list(root["targets"], field="targets")
    if len(raw_targets) != 2:
        raise RulesetGovernanceError("manifest must declare exactly two governance targets")

    targets: list[RulesetTarget] = []
    identities: set[tuple[str, int]] = set()
    for index, raw in enumerate(raw_targets):
        item = _plain_dict(raw, field=f"targets[{index}]")
        if set(item) != {"scope", "owner", "repository", "ruleset_id", "name"}:
            raise RulesetGovernanceError(f"targets[{index}] has an unexpected key set")
        scope = item["scope"]
        owner = item["owner"]
        repository = item["repository"]
        ruleset_id = item["ruleset_id"]
        name = item["name"]
        if scope not in {"organization", "repository"}:
            raise RulesetGovernanceError(f"targets[{index}].scope is unsupported")
        if owner != ORGANIZATION or type(ruleset_id) is not int or ruleset_id <= 0:
            raise RulesetGovernanceError(f"targets[{index}] identity is invalid")
        if type(name) is not str or not name.strip():
            raise RulesetGovernanceError(f"targets[{index}].name is invalid")
        if scope == "organization" and repository is not None:
            raise RulesetGovernanceError("organization target repository must be null")
        if scope == "repository" and (type(repository) is not str or not repository):
            raise RulesetGovernanceError("repository target repository must be non-empty")
        identity = (scope, ruleset_id)
        if identity in identities:
            raise RulesetGovernanceError("manifest contains a duplicate ruleset target")
        identities.add(identity)
        targets.append(RulesetTarget(scope, owner, repository, ruleset_id, name))

    if {target.scope for target in targets} != {"organization", "repository"}:
        raise RulesetGovernanceError("manifest must contain one target per supported scope")
    return tuple(targets)


def _gh_command(method: str, endpoint: str) -> list[str]:
    """Build one versioned GitHub CLI command for the reviewed REST boundary."""

    return [
        "gh",
        "api",
        "--method",
        method,
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        endpoint,
    ]


def _run_gh_json(
    method: str,
    endpoint: str,
    *,
    body: dict[str, Any] | None = None,
) -> Any:
    """Call GitHub REST and decode JSON without exposing credential diagnostics."""

    command = _gh_command(method, endpoint)
    if body is not None:
        command.extend(["--input", "-"])
    completed = subprocess.run(
        command,
        check=False,
        input=None if body is None else json.dumps(body, separators=(",", ":")),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RulesetGovernanceError(f"GitHub API request failed for {endpoint}")
    return json.loads(completed.stdout)


def _gh_api(
    method: str,
    endpoint: str,
    *,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call GitHub REST and require an object response."""

    return _plain_dict(
        _run_gh_json(method, endpoint, body=body),
        field=f"GitHub response for {endpoint}",
    )


def _gh_api_list(method: str, endpoint: str) -> list[Any]:
    """Call GitHub REST and require an array response."""

    return _plain_list(
        _run_gh_json(method, endpoint),
        field=f"GitHub response for {endpoint}",
    )


def _current_main_sha() -> str:
    """Return the exact protected control-repository main SHA from GitHub."""

    payload = _gh_api("GET", f"repos/{CONTROL_REPOSITORY}/git/ref/heads/main")
    object_data = _plain_dict(payload.get("object"), field="main ref object")
    sha = str(object_data.get("sha") or "").lower()
    if not GIT_SHA_RE.fullmatch(sha):
        raise RulesetGovernanceError("protected main returned a malformed SHA")
    return sha


def _assert_current_main(expected_main_sha: str) -> None:
    """Fail closed when the privileged run no longer represents current main."""

    if not GIT_SHA_RE.fullmatch(expected_main_sha):
        raise RulesetGovernanceError("expected protected main SHA is malformed")
    if _current_main_sha() != expected_main_sha:
        raise RulesetGovernanceError(
            "protected main advanced; refusing stale governance mutation"
        )


def _history_version_id(entry: Any) -> int:
    """Return one positive ruleset-history version ID or fail closed."""

    item = _plain_dict(entry, field="ruleset history entry")
    version_id = item.get("version_id")
    if type(version_id) is not int or version_id <= 0:
        raise RulesetGovernanceError("ruleset history version identity is malformed")
    return version_id


def _latest_history_version(target: RulesetTarget) -> int:
    """Return the newest immutable history version before mutation."""

    history = _gh_api_list("GET", f"{target.history_endpoint}?per_page=1")
    if not history:
        raise RulesetGovernanceError("ruleset history is empty")
    return _history_version_id(history[0])


def _assert_target_provenance(live: dict[str, Any], target: RulesetTarget) -> None:
    """Require immutable target provenance while allowing editable history fields."""

    expected = {
        "id": target.ruleset_id,
        "target": "branch",
        "source_type": target.source_type,
        "source": target.source,
    }
    mismatches = [key for key, value in expected.items() if live.get(key) != value]
    if mismatches:
        raise RulesetGovernanceError(
            f"{target.scope} ruleset identity drift: {', '.join(sorted(mismatches))}"
        )


def _history_version_state(target: RulesetTarget, version_id: int) -> dict[str, Any]:
    """Return one historical state after proving it belongs to the exact target."""

    payload = _gh_api("GET", target.history_version_endpoint(version_id))
    state = _plain_dict(payload.get("state"), field="ruleset history version state")
    _assert_target_provenance(state, target)
    return state


def _assert_identity(live: dict[str, Any], target: RulesetTarget) -> None:
    """Require current live state to retain the reviewed editable identity too."""

    _assert_target_provenance(live, target)
    expected = {"name": target.name, "enforcement": "active"}
    mismatches = [key for key, value in expected.items() if live.get(key) != value]
    if mismatches:
        raise RulesetGovernanceError(
            f"{target.scope} ruleset identity drift: {', '.join(sorted(mismatches))}"
        )


def _editable_projection(live: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the fields accepted by GitHub's ruleset update endpoint."""

    required = {
        "name",
        "target",
        "enforcement",
        "bypass_actors",
        "conditions",
        "rules",
    }
    missing = sorted(required.difference(live))
    if missing:
        raise RulesetGovernanceError(
            f"ruleset payload misses editable fields: {', '.join(missing)}"
        )
    projection = {key: copy.deepcopy(live[key]) for key in required}
    _plain_list(projection["bypass_actors"], field="bypass_actors")
    _plain_dict(projection["conditions"], field="conditions")
    _plain_list(projection["rules"], field="rules")
    return projection


def _desired_payload(live: dict[str, Any], target: RulesetTarget) -> dict[str, Any]:
    """Build the exact safe update body while preserving unrelated live controls."""

    _assert_identity(live, target)
    desired = _editable_projection(live)
    desired["bypass_actors"] = []

    pull_request_rules = [
        rule
        for rule in desired["rules"]
        if type(rule) is dict and rule.get("type") == "pull_request"
    ]
    if len(pull_request_rules) != 1:
        raise RulesetGovernanceError("ruleset must contain exactly one pull_request rule")
    parameters = _plain_dict(
        pull_request_rules[0].get("parameters"), field="pull_request.parameters"
    )
    required_parameters = {
        "required_approving_review_count": int,
        "require_code_owner_review": bool,
        "require_last_push_approval": bool,
        "required_reviewers": list,
        "allowed_merge_methods": list,
    }
    for field, expected_type in required_parameters.items():
        if type(parameters.get(field)) is not expected_type:
            raise RulesetGovernanceError(
                f"pull_request.parameters.{field} has invalid type"
            )

    parameters["required_approving_review_count"] = 0
    parameters["require_code_owner_review"] = False
    parameters["require_last_push_approval"] = False
    parameters["required_reviewers"] = []
    parameters["allowed_merge_methods"] = list(DESIRED_MERGE_METHODS)
    return desired


def _recover_displaced_history_state(
    target: RulesetTarget,
    *,
    current_version: int,
    current_payload: dict[str, Any],
    displaced_version: int,
) -> None:
    """Restore the newest state displaced by our unsafe PUT without hiding races.

    GitHub offers no conditional ruleset PUT. Each recovery write therefore
    verifies immutable history immediately afterward. If an administrator write
    slipped between the recovery GET and PUT, that displaced history version
    becomes the next recovery target. A newer live state observed before a
    recovery write is never overwritten. The loop is bounded and fails closed.
    """

    for _attempt in range(COLLISION_RECOVERY_LIMIT):
        displaced_state = _history_version_state(target, displaced_version)
        displaced_payload = _editable_projection(displaced_state)
        live = _gh_api("GET", target.endpoint)
        _assert_target_provenance(live, target)
        if _editable_projection(live) != current_payload:
            raise RulesetGovernanceError(
                "concurrent ruleset history detected but live state advanced again; refusing recovery"
            )

        _gh_api("PUT", target.endpoint, body=displaced_payload)
        history = _gh_api_list("GET", f"{target.history_endpoint}?per_page=2")
        if len(history) < 2:
            raise RulesetGovernanceError(
                "ruleset collision recovery history did not expose a predecessor"
            )
        recovery_version = _history_version_id(history[0])
        recovery_predecessor = _history_version_id(history[1])
        recovery_state = _history_version_state(target, recovery_version)
        if _editable_projection(recovery_state) != displaced_payload:
            raise RulesetGovernanceError(
                "ruleset collision recovery latest history does not match restore write"
            )

        restored = _gh_api("GET", target.endpoint)
        _assert_target_provenance(restored, target)
        if _editable_projection(restored) != displaced_payload:
            raise RulesetGovernanceError(
                "concurrent ruleset collision rollback did not converge"
            )
        if recovery_predecessor == current_version:
            return

        current_version = recovery_version
        current_payload = displaced_payload
        displaced_version = recovery_predecessor

    raise RulesetGovernanceError(
        "ruleset collision recovery exceeded bounded attempts under concurrent writes"
    )


def _verify_ruleset_history_transition(
    target: RulesetTarget,
    baseline_version: int,
    desired: dict[str, Any],
) -> None:
    """Detect hidden pre-PUT edits and restore the newest displaced state safely.

    The newest history state must equal our reviewed body and its immediate
    predecessor must be the version sampled before the final live read. If a
    version intervened, recovery follows immutable history and verifies every
    restore write so a second administrator edit cannot be silently overwritten.
    """

    history = _gh_api_list("GET", f"{target.history_endpoint}?per_page=3")
    if len(history) < 2:
        raise RulesetGovernanceError("ruleset history did not expose a predecessor")
    newest_id = _history_version_id(history[0])
    predecessor_id = _history_version_id(history[1])
    if newest_id == baseline_version:
        raise RulesetGovernanceError("ruleset mutation is not visible in history")

    newest_state = _history_version_state(target, newest_id)
    if _editable_projection(newest_state) != desired:
        raise RulesetGovernanceError("latest ruleset history does not match reviewed mutation")
    if predecessor_id == baseline_version:
        return

    _recover_displaced_history_state(
        target,
        current_version=newest_id,
        current_payload=desired,
        displaced_version=predecessor_id,
    )
    raise RulesetGovernanceError(
        "concurrent ruleset history detected; restored newest displaced administrator state"
    )


def _reconcile_target(
    target: RulesetTarget,
    *,
    verify_only: bool,
    expected_main_sha: str | None = None,
) -> bool:
    """Verify or reconcile one target; return whether a mutation was performed."""

    first = _gh_api("GET", target.endpoint)
    desired = _desired_payload(first, target)
    if _editable_projection(first) == desired:
        return False
    if verify_only:
        raise RulesetGovernanceError(
            f"{target.scope} ruleset governance drift remains"
        )

    baseline_version: int | None = None
    if expected_main_sha is not None:
        _assert_current_main(expected_main_sha)
        baseline_version = _latest_history_version(target)
    second = _gh_api("GET", target.endpoint)
    if _editable_projection(second) != _editable_projection(first):
        raise RulesetGovernanceError(
            f"{target.scope} ruleset changed concurrently; refusing to overwrite"
        )
    _assert_identity(second, target)
    if expected_main_sha is not None:
        _assert_current_main(expected_main_sha)
    _gh_api("PUT", target.endpoint, body=desired)
    after = _gh_api("GET", target.endpoint)
    _assert_identity(after, target)
    if _editable_projection(after) != desired:
        raise RulesetGovernanceError(f"{target.scope} ruleset did not converge")
    if baseline_version is not None:
        _verify_ruleset_history_transition(target, baseline_version, desired)
    if expected_main_sha is not None:
        _assert_current_main(expected_main_sha)
    return True


def reconcile(
    targets: tuple[RulesetTarget, ...],
    *,
    verify_only: bool,
    expected_main_sha: str | None = None,
) -> int:
    """Reconcile all targets and return the number of successful mutations."""

    mutations = 0
    for target in sorted(targets, key=lambda item: item.scope == "organization"):
        if expected_main_sha is None:
            mutated = _reconcile_target(target, verify_only=verify_only)
        else:
            mutated = _reconcile_target(
                target,
                verify_only=verify_only,
                expected_main_sha=expected_main_sha,
            )
        mutations += int(mutated)
    return mutations


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for validation, apply, or verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/ruleset-governance.json"),
        help="Reviewed desired-state target manifest.",
    )
    parser.add_argument(
        "--expected-main-sha",
        help="Exact trusted protected-main SHA for privileged mutation.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Validate the manifest or reconcile exact live ruleset governance."""

    args = _parse_args(argv)
    targets = load_manifest(args.manifest)
    if args.validate_only:
        print(f"validated {len(targets)} ruleset governance targets")
        return 0
    if not os.environ.get("GH_TOKEN"):
        raise RulesetGovernanceError(
            "GH_TOKEN is required for live ruleset governance"
        )
    if (
        not args.verify_only
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and not args.expected_main_sha
    ):
        raise RulesetGovernanceError(
            "expected protected main SHA is required for Actions mutation"
        )
    if args.expected_main_sha is None:
        mutations = reconcile(targets, verify_only=args.verify_only)
    else:
        mutations = reconcile(
            targets,
            verify_only=args.verify_only,
            expected_main_sha=args.expected_main_sha,
        )
    verb = "verified" if args.verify_only else "reconciled"
    print(f"{verb} {len(targets)} ruleset governance targets; mutations={mutations}")
    return 0


def cli() -> None:
    """Execute the command-line boundary with concise fail-closed diagnostics."""

    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, RulesetGovernanceError) as exc:
        print(f"ruleset governance reconciliation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess smoke test
    cli()
