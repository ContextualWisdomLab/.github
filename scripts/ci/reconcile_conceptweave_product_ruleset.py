#!/usr/bin/env python3
"""Stage ConceptWeave Product ruleset enforcement without bootstrap deadlock."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.ci.reconcile_ruleset_governance import (
    API_REQUEST_TIMEOUT_SECONDS,
    API_VERSION,
    AmbiguousRulesetWriteError,
    RulesetGovernanceError,
    RulesetTarget,
    _assert_current_main,
    _assert_target_provenance,
    _confirm_ambiguous_put,
    _editable_projection,
    _gh_api,
    _gh_api_list,
    _history_version_state,
    _latest_history_version,
    _plain_dict,
    _plain_list,
    _verify_ruleset_history_transition,
)

ORGANIZATION = "ContextualWisdomLab"
TARGET_REPOSITORY = "ConceptWeave"
TARGET_FULL_NAME = f"{ORGANIZATION}/{TARGET_REPOSITORY}"
TARGET_BRANCH = "main"
RULESET_NAME = "ConceptWeave Product acceptance"
PRODUCT_WORKFLOW_PATH = ".github/workflows/product.yml"
PRODUCT_WORKFLOW_NAME = "Product"
PRODUCT_CHECK = "Product acceptance"
METADATA_ONLY_CHECK = "Product metadata-only"
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def load_product_manifest(path: Path) -> dict[str, Any]:
    """Load and strictly validate the reviewed ConceptWeave Product manifest."""

    root = _plain_dict(json.loads(path.read_text(encoding="utf-8")), field="product manifest")
    expected_keys = {
        "schema_version",
        "target_repository",
        "target_branch",
        "ruleset_name",
        "ruleset_id",
        "required_check",
        "forbidden_check",
    }
    if set(root) != expected_keys:
        raise RulesetGovernanceError("Product manifest has an unexpected key set")
    expected = {
        "schema_version": 1,
        "target_repository": TARGET_FULL_NAME,
        "target_branch": TARGET_BRANCH,
        "ruleset_name": RULESET_NAME,
        "required_check": PRODUCT_CHECK,
        "forbidden_check": METADATA_ONLY_CHECK,
    }
    mismatches = [key for key, value in expected.items() if root.get(key) != value]
    if mismatches:
        raise RulesetGovernanceError(
            f"Product manifest has unsupported fields: {', '.join(sorted(mismatches))}"
        )
    ruleset_id = root["ruleset_id"]
    if ruleset_id is not None and (type(ruleset_id) is not int or ruleset_id <= 0):
        raise RulesetGovernanceError("Product manifest ruleset_id must be null or positive")
    return root


def _target(ruleset_id: int) -> RulesetTarget:
    """Build the exact repository-owned ruleset identity after source adoption."""

    if type(ruleset_id) is not int or ruleset_id <= 0:
        raise RulesetGovernanceError("Product ruleset identity must be positive")
    return RulesetTarget(
        scope="repository",
        owner=ORGANIZATION,
        repository=TARGET_REPOSITORY,
        ruleset_id=ruleset_id,
        name=RULESET_NAME,
    )


def _desired(*, enforcement: str, integration_id: int | None) -> dict[str, Any]:
    """Return the exact evaluate or active Product ruleset mutation body."""

    if enforcement not in {"evaluate", "active"}:
        raise RulesetGovernanceError("Product ruleset enforcement is unsupported")
    check: dict[str, Any] = {"context": PRODUCT_CHECK}
    if integration_id is not None:
        if type(integration_id) is not int or integration_id <= 0:
            raise RulesetGovernanceError("Product integration identity must be positive")
        check["integration_id"] = integration_id
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": enforcement,
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "include": [f"refs/heads/{TARGET_BRANCH}"],
                "exclude": [],
            }
        },
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [check],
                    "strict_required_status_checks_policy": True,
                },
            }
        ],
    }


def _assert_shape(
    live: dict[str, Any],
    target: RulesetTarget,
    *,
    enforcement: str,
    integration_id: int | None,
) -> None:
    """Require exact provenance and policy for the dedicated Product ruleset."""

    _assert_target_provenance(live, target)
    if live.get("name") != RULESET_NAME:
        raise RulesetGovernanceError("Product ruleset name drifted")
    if _editable_projection(live) != _desired(
        enforcement=enforcement,
        integration_id=integration_id,
    ):
        raise RulesetGovernanceError(
            f"Product ruleset does not match reviewed {enforcement} policy"
        )


def _repository_rulesets() -> list[dict[str, Any]]:
    """List repository-owned rulesets only, excluding inherited organization rules."""

    payload = _gh_api_list(
        "GET",
        f"repos/{TARGET_FULL_NAME}/rulesets?includes_parents=false&per_page=100",
    )
    result: list[dict[str, Any]] = []
    for item in payload:
        live = _plain_dict(item, field="repository ruleset list entry")
        if live.get("source_type") != "Repository" or live.get("source") != TARGET_FULL_NAME:
            raise RulesetGovernanceError(
                "repository-only Product ruleset discovery returned foreign provenance"
            )
        result.append(live)
    return result


def _named_ruleset() -> dict[str, Any] | None:
    """Return the one exact-name repository ruleset or fail on duplicate identity."""

    matches = [item for item in _repository_rulesets() if item.get("name") == RULESET_NAME]
    if len(matches) > 1:
        raise RulesetGovernanceError("multiple ConceptWeave Product rulesets are ambiguous")
    return matches[0] if matches else None


def _live(target: RulesetTarget) -> dict[str, Any]:
    """Fetch one pinned Product ruleset from its immutable repository identity."""

    payload = _gh_api("GET", target.endpoint)
    _assert_target_provenance(payload, target)
    return payload


def _active_integration_id(live: dict[str, Any]) -> int:
    """Return the exact integration identity bound by an active Product policy."""

    rules = _plain_list(live.get("rules"), field="Product rules")
    if len(rules) != 1:
        raise RulesetGovernanceError("active Product ruleset must contain one rule")
    rule = _plain_dict(rules[0], field="Product required-status rule")
    parameters = _plain_dict(
        rule.get("parameters"), field="Product required-status parameters"
    )
    checks = _plain_list(
        parameters.get("required_status_checks"),
        field="Product required status checks",
    )
    if len(checks) != 1:
        raise RulesetGovernanceError("active Product ruleset must require one check")
    check = _plain_dict(checks[0], field="Product required status check")
    integration_id = check.get("integration_id")
    if type(integration_id) is not int or integration_id <= 0:
        raise RulesetGovernanceError(
            "active Product ruleset lacks a positive integration identity"
        )
    return integration_id


def verify_product_ruleset(manifest: dict[str, Any]) -> str:
    """Verify absent, evaluate, or active live state without mutating governance."""

    pinned_id = manifest["ruleset_id"]
    named = _named_ruleset()
    if pinned_id is None:
        if named is None:
            return "absent"
        raise RulesetGovernanceError(
            f"Product ruleset exists as id={named.get('id')}; pin it in reviewed source"
        )
    target = _target(pinned_id)
    if named is None or named.get("id") != pinned_id:
        raise RulesetGovernanceError("pinned Product ruleset is absent or name-drifted")
    live = _live(target)
    if live.get("enforcement") == "evaluate":
        _assert_shape(live, target, enforcement="evaluate", integration_id=None)
        return "evaluate"
    if live.get("enforcement") == "active":
        integration_id = _active_integration_id(live)
        _assert_shape(
            live,
            target,
            enforcement="active",
            integration_id=integration_id,
        )
        return "active"
    raise RulesetGovernanceError("Product ruleset enforcement is unsupported")


def _create_evaluate_ruleset() -> dict[str, Any]:
    """Create the evaluate-only Product ruleset with ambiguous-result settlement."""

    endpoint = f"repos/{TARGET_FULL_NAME}/rulesets"
    body = _desired(enforcement="evaluate", integration_id=None)
    command = [
        "gh",
        "api",
        "--method",
        "POST",
        "-H",
        f"X-GitHub-Api-Version: {API_VERSION}",
        endpoint,
        "--input",
        "-",
    ]
    ambiguous: BaseException | None = None
    try:
        completed = subprocess.run(
            command,
            check=False,
            input=json.dumps(body, separators=(",", ":")),
            capture_output=True,
            text=True,
            timeout=API_REQUEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        ambiguous = exc
    else:
        if completed.returncode == 0:
            try:
                return _plain_dict(
                    json.loads(completed.stdout),
                    field="Product ruleset create response",
                )
            except json.JSONDecodeError as exc:
                ambiguous = exc
        else:
            ambiguous = AmbiguousRulesetWriteError(
                "GitHub Product ruleset POST outcome is ambiguous"
            )

    settled = _named_ruleset()
    if settled is None:
        raise RulesetGovernanceError(
            "Product ruleset create outcome remains ambiguous with no live identity"
        ) from ambiguous
    ruleset_id = settled.get("id")
    target = _target(ruleset_id)
    live = _live(target)
    _assert_shape(live, target, enforcement="evaluate", integration_id=None)
    return live


def bootstrap_product_ruleset(
    manifest: dict[str, Any],
    *,
    expected_main_sha: str,
) -> int:
    """Create evaluate policy or verify the exact reviewed source-adopted identity."""

    _assert_current_main(expected_main_sha)
    pinned_id = manifest["ruleset_id"]
    named = _named_ruleset()
    if pinned_id is not None:
        target = _target(pinned_id)
        if named is None or named.get("id") != pinned_id:
            raise RulesetGovernanceError("pinned Product ruleset is absent or name-drifted")
        live = _live(target)
        if live.get("enforcement") == "active":
            integration_id = _active_integration_id(live)
            _assert_shape(
                live,
                target,
                enforcement="active",
                integration_id=integration_id,
            )
        else:
            _assert_shape(live, target, enforcement="evaluate", integration_id=None)
        _assert_current_main(expected_main_sha)
        return pinned_id

    if named is not None:
        raise RulesetGovernanceError(
            f"Product ruleset exists as id={named.get('id')}; pin it before mutation"
        )
    _assert_current_main(expected_main_sha)
    created = _create_evaluate_ruleset()
    ruleset_id = created.get("id")
    target = _target(ruleset_id)
    _assert_shape(created, target, enforcement="evaluate", integration_id=None)
    version = _latest_history_version(target)
    history_state = _history_version_state(target, version)
    _assert_shape(history_state, target, enforcement="evaluate", integration_id=None)
    _assert_current_main(expected_main_sha)
    return ruleset_id


def _decode_workflow(payload: dict[str, Any]) -> str:
    """Decode an exact GitHub contents response for the Product workflow."""

    if payload.get("type") != "file" or payload.get("encoding") != "base64":
        raise RulesetGovernanceError("Product workflow contents are not a base64 file")
    content = payload.get("content")
    if type(content) is not str:
        raise RulesetGovernanceError("Product workflow content is malformed")
    normalized = content.replace("\r", "").replace("\n", "")
    try:
        return base64.b64decode(normalized, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RulesetGovernanceError("Product workflow content is invalid UTF-8 base64") from exc


def _assert_base_product_workflow(base_sha: str) -> None:
    """Require the protected canary base to contain both reviewed Product identities."""

    payload = _gh_api(
        "GET",
        f"repos/{TARGET_FULL_NAME}/contents/{PRODUCT_WORKFLOW_PATH}?ref={base_sha}",
    )
    text = _decode_workflow(payload)
    for fragment in ("name: Product", "'Product acceptance'", "'Product metadata-only'"):
        if fragment not in text:
            raise RulesetGovernanceError(
                "protected-base Product workflow lacks reviewed check identities"
            )


def _canary_integration_id(*, pr_number: int, run_id: int) -> int:
    """Prove an exact current-base successful Product canary and return its app ID."""

    if pr_number <= 0 or run_id <= 0:
        raise RulesetGovernanceError("canary identities must be positive")
    pr = _gh_api("GET", f"repos/{TARGET_FULL_NAME}/pulls/{pr_number}")
    if pr.get("state") != "open" or pr.get("draft") is True:
        raise RulesetGovernanceError("Product canary PR must be open and non-draft")
    head = _plain_dict(pr.get("head"), field="Product canary head")
    base = _plain_dict(pr.get("base"), field="Product canary base")
    head_sha = str(head.get("sha") or "").lower()
    base_sha = str(base.get("sha") or "").lower()
    if not GIT_SHA_RE.fullmatch(head_sha) or not GIT_SHA_RE.fullmatch(base_sha):
        raise RulesetGovernanceError("Product canary returned malformed head/base SHA")
    if base.get("ref") != TARGET_BRANCH:
        raise RulesetGovernanceError("Product canary does not target protected main")
    if _gh_api(
        "GET",
        f"repos/{TARGET_FULL_NAME}/git/ref/heads/{TARGET_BRANCH}",
    ).get("object", {}).get("sha") != base_sha:
        raise RulesetGovernanceError("Product canary base is not current protected main")
    _assert_base_product_workflow(base_sha)

    run = _gh_api("GET", f"repos/{TARGET_FULL_NAME}/actions/runs/{run_id}")
    if (
        run.get("name") != PRODUCT_WORKFLOW_NAME
        or run.get("event") != "pull_request"
        or run.get("head_sha") != head_sha
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        raise RulesetGovernanceError(
            "canary run is not exact-head terminal Product success"
        )
    run_prs = _plain_list(run.get("pull_requests"), field="Product canary run pull_requests")
    bound = False
    for item in run_prs:
        run_pr = _plain_dict(item, field="Product canary run pull request")
        run_head = _plain_dict(run_pr.get("head"), field="Product canary run head")
        run_base = _plain_dict(run_pr.get("base"), field="Product canary run base")
        if (
            run_pr.get("number") == pr_number
            and run_head.get("sha") == head_sha
            and run_base.get("sha") == base_sha
        ):
            bound = True
            break
    if not bound:
        raise RulesetGovernanceError("Product canary run is not bound to live PR head/base")

    jobs = _plain_list(
        _gh_api(
            "GET",
            f"repos/{TARGET_FULL_NAME}/actions/runs/{run_id}/jobs?filter=latest&per_page=100",
        ).get("jobs"),
        field="Product canary jobs",
    )
    acceptance = [
        _plain_dict(job, field="Product canary job")
        for job in jobs
        if _plain_dict(job, field="Product canary job").get("name") == PRODUCT_CHECK
    ]
    if len(acceptance) != 1:
        raise RulesetGovernanceError(
            "Product canary must contain exactly one Product acceptance job"
        )
    if (
        acceptance[0].get("status") != "completed"
        or acceptance[0].get("conclusion") != "success"
    ):
        raise RulesetGovernanceError("Product acceptance canary job is not successful")

    checks = _plain_list(
        _gh_api(
            "GET",
            f"repos/{TARGET_FULL_NAME}/commits/{head_sha}/check-runs"
            "?check_name=Product%20acceptance&filter=latest&per_page=100",
        ).get("check_runs"),
        field="Product acceptance check runs",
    )
    suite_id = run.get("check_suite_id")
    matched: list[dict[str, Any]] = []
    for item in checks:
        check = _plain_dict(item, field="Product acceptance check")
        suite = _plain_dict(check.get("check_suite"), field="Product acceptance check suite")
        if (
            check.get("name") == PRODUCT_CHECK
            and suite.get("id") == suite_id
            and check.get("status") == "completed"
            and check.get("conclusion") == "success"
        ):
            matched.append(check)
    if len(matched) != 1:
        raise RulesetGovernanceError(
            "Product canary lacks one exact successful Product acceptance check"
        )
    app = _plain_dict(matched[0].get("app"), field="Product acceptance app")
    integration_id = app.get("id")
    if type(integration_id) is not int or integration_id <= 0:
        raise RulesetGovernanceError(
            "Product acceptance check lacks a positive integration identity"
        )
    return integration_id


def activate_product_ruleset(
    manifest: dict[str, Any],
    *,
    expected_main_sha: str,
    canary_pr: int,
    canary_run_id: int,
) -> int:
    """Promote evaluate to active only after exact current-base Product evidence."""

    _assert_current_main(expected_main_sha)
    pinned_id = manifest["ruleset_id"]
    if type(pinned_id) is not int or pinned_id <= 0:
        raise RulesetGovernanceError("Product activation requires reviewed ruleset_id adoption")
    target = _target(pinned_id)
    named = _named_ruleset()
    if named is None or named.get("id") != pinned_id:
        raise RulesetGovernanceError("pinned Product ruleset is absent or name-drifted")
    first = _live(target)
    if first.get("enforcement") == "active":
        raise RulesetGovernanceError("Product ruleset is already active; use verify")
    _assert_shape(first, target, enforcement="evaluate", integration_id=None)

    integration_id = _canary_integration_id(
        pr_number=canary_pr,
        run_id=canary_run_id,
    )
    desired = _desired(enforcement="active", integration_id=integration_id)
    baseline_version = _latest_history_version(target)
    _assert_current_main(expected_main_sha)
    second = _live(target)
    if _editable_projection(second) != _editable_projection(first):
        raise RulesetGovernanceError(
            "Product ruleset changed concurrently; refusing activation"
        )
    _assert_shape(second, target, enforcement="evaluate", integration_id=None)
    _assert_current_main(expected_main_sha)

    history_verified = False
    try:
        _gh_api("PUT", target.endpoint, body=desired)
    except (AmbiguousRulesetWriteError, subprocess.TimeoutExpired):
        after = _confirm_ambiguous_put(
            target,
            baseline_version=baseline_version,
            desired=desired,
            expected_main_sha=expected_main_sha,
        )
        history_verified = True
    else:
        after = _live(target)

    _assert_shape(
        after,
        target,
        enforcement="active",
        integration_id=integration_id,
    )
    if not history_verified:
        _verify_ruleset_history_transition(
            target,
            baseline_version,
            desired,
            expected_main_sha=None,
        )
    _assert_current_main(expected_main_sha)
    return integration_id


def _positive_int(value: str) -> int:
    """Parse one strictly positive CLI integer."""

    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse source validation, live verification, bootstrap, and activation modes."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/conceptweave-product-ruleset.json"),
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("validate", "verify", "bootstrap", "activate"),
    )
    parser.add_argument("--expected-main-sha")
    parser.add_argument("--canary-pr", type=_positive_int)
    parser.add_argument("--canary-run-id", type=_positive_int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Execute the requested fail-closed Product ruleset lifecycle phase."""

    args = _parse_args(argv)
    manifest = load_product_manifest(args.manifest)
    if args.mode == "validate":
        print("validated ConceptWeave Product ruleset manifest")
        return 0
    if not os.environ.get("GH_TOKEN"):
        raise RulesetGovernanceError("GH_TOKEN is required for live Product governance")
    if args.mode == "verify":
        print(f"Product ruleset stage={verify_product_ruleset(manifest)}")
        return 0
    if os.environ.get("CWL_RULESET_RECONCILE_ENABLED") != "true":
        raise RulesetGovernanceError("privileged ruleset reconciliation is disabled")
    if not args.expected_main_sha:
        raise RulesetGovernanceError("expected protected main SHA is required for mutation")
    if args.mode == "bootstrap":
        ruleset_id = bootstrap_product_ruleset(
            manifest,
            expected_main_sha=args.expected_main_sha,
        )
        print(f"Product ruleset id={ruleset_id}")
        if manifest["ruleset_id"] is None:
            print("reviewed source adoption required before further mutation")
        return 0
    if args.canary_pr is None or args.canary_run_id is None:
        raise RulesetGovernanceError("activate requires canary PR and run IDs")
    integration_id = activate_product_ruleset(
        manifest,
        expected_main_sha=args.expected_main_sha,
        canary_pr=args.canary_pr,
        canary_run_id=args.canary_run_id,
    )
    print(f"Product ruleset active integration_id={integration_id}")
    return 0


def cli() -> None:
    """Run the command-line boundary with concise fail-closed diagnostics."""

    try:
        raise SystemExit(main())
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
        RulesetGovernanceError,
    ) as exc:
        print(f"ConceptWeave Product ruleset reconciliation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":  # pragma: no cover - subprocess contract
    cli()
