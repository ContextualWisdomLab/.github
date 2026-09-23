#!/usr/bin/env python3
"""Govern the ConceptWeave Product workflow as a scoped organization branch ruleset."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime
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
TARGET_REPOSITORY_ID = 1353201939
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
    """Build the exact organization-owned Product ruleset identity."""

    if type(ruleset_id) is not int or ruleset_id <= 0:
        raise RulesetGovernanceError("Product ruleset identity must be positive")
    return RulesetTarget(
        scope="organization",
        owner=ORGANIZATION,
        repository=None,
        ruleset_id=ruleset_id,
        name=RULESET_NAME,
    )


def _desired(*, enforcement: str) -> dict[str, Any]:
    """Return the exact evaluate or active organization workflow rule."""

    if enforcement not in {"evaluate", "active"}:
        raise RulesetGovernanceError("Product ruleset enforcement is unsupported")
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": enforcement,
        "bypass_actors": [],
        "conditions": {
            "repository_id": {"repository_ids": [TARGET_REPOSITORY_ID]},
            "ref_name": {
                "include": [f"refs/heads/{TARGET_BRANCH}"],
                "exclude": [],
            },
        },
        "rules": [
            {
                "type": "workflows",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "workflows": [
                        {
                            "repository_id": TARGET_REPOSITORY_ID,
                            "path": PRODUCT_WORKFLOW_PATH,
                            "ref": f"refs/heads/{TARGET_BRANCH}",
                        }
                    ],
                },
            }
        ],
    }


def _assert_shape(
    live: dict[str, Any],
    target: RulesetTarget,
    *,
    enforcement: str,
) -> None:
    """Require exact provenance and policy for the dedicated Product ruleset."""

    _assert_target_provenance(live, target)
    if live.get("name") != RULESET_NAME:
        raise RulesetGovernanceError("Product ruleset name drifted")
    if _editable_projection(live) != _desired(enforcement=enforcement):
        raise RulesetGovernanceError(
            f"Product ruleset does not match reviewed {enforcement} policy"
        )


def _organization_rulesets() -> list[dict[str, Any]]:
    """List organization-owned rulesets and reject foreign provenance."""

    payload = _gh_api_list("GET", f"orgs/{ORGANIZATION}/rulesets?per_page=100")
    result: list[dict[str, Any]] = []
    for item in payload:
        live = _plain_dict(item, field="organization ruleset list entry")
        if live.get("source_type") != "Organization" or live.get("source") != ORGANIZATION:
            raise RulesetGovernanceError(
                "organization Product ruleset discovery returned foreign provenance"
            )
        result.append(live)
    return result


def _named_ruleset() -> dict[str, Any] | None:
    """Return the one exact-name organization ruleset or fail on ambiguity."""

    matches = [item for item in _organization_rulesets() if item.get("name") == RULESET_NAME]
    if len(matches) > 1:
        raise RulesetGovernanceError("multiple ConceptWeave Product rulesets are ambiguous")
    return matches[0] if matches else None


def _live(target: RulesetTarget) -> dict[str, Any]:
    """Fetch one pinned Product ruleset from its organization identity."""

    payload = _gh_api("GET", target.endpoint)
    _assert_target_provenance(payload, target)
    return payload


def verify_product_ruleset(manifest: dict[str, Any]) -> str:
    """Verify absent, evaluate, or active live state without mutation."""

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
    enforcement = live.get("enforcement")
    if enforcement not in {"evaluate", "active"}:
        raise RulesetGovernanceError("Product ruleset enforcement is unsupported")
    _assert_shape(live, target, enforcement=enforcement)
    return str(enforcement)


def _create_evaluate_ruleset() -> dict[str, Any]:
    """Create the evaluate-only organization ruleset with ambiguous-result settlement."""

    endpoint = f"orgs/{ORGANIZATION}/rulesets"
    body = _desired(enforcement="evaluate")
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
    _assert_shape(live, target, enforcement="evaluate")
    return live


def _target_main_sha() -> str:
    """Read and validate the exact protected ConceptWeave main revision."""

    payload = _gh_api("GET", f"repos/{TARGET_FULL_NAME}/git/ref/heads/{TARGET_BRANCH}")
    obj = _plain_dict(payload.get("object"), field="ConceptWeave main ref object")
    sha = str(obj.get("sha") or "").lower()
    if not GIT_SHA_RE.fullmatch(sha):
        raise RulesetGovernanceError("ConceptWeave protected main SHA is malformed")
    return sha


def _assert_target_main(expected_sha: str) -> None:
    """Fail when ConceptWeave protected main is not the reviewed canary base."""

    if _target_main_sha() != expected_sha:
        raise RulesetGovernanceError("ConceptWeave protected main advanced")


def bootstrap_product_ruleset(
    manifest: dict[str, Any],
    *,
    expected_main_sha: str,
) -> int:
    """Create evaluate policy or verify the reviewed source-adopted identity."""

    _assert_current_main(expected_main_sha)
    pinned_id = manifest["ruleset_id"]
    named = _named_ruleset()
    if pinned_id is not None:
        target = _target(pinned_id)
        if named is None or named.get("id") != pinned_id:
            raise RulesetGovernanceError("pinned Product ruleset is absent or name-drifted")
        live = _live(target)
        enforcement = live.get("enforcement")
        if enforcement not in {"evaluate", "active"}:
            raise RulesetGovernanceError("Product ruleset enforcement is unsupported")
        _assert_shape(live, target, enforcement=enforcement)
        _assert_current_main(expected_main_sha)
        return pinned_id

    if named is not None:
        raise RulesetGovernanceError(
            f"Product ruleset exists as id={named.get('id')}; pin it before mutation"
        )
    target_main_sha = _target_main_sha()
    _assert_base_product_workflow(target_main_sha)
    _assert_current_main(expected_main_sha)
    _assert_target_main(target_main_sha)
    created = _create_evaluate_ruleset()
    ruleset_id = created.get("id")
    target = _target(ruleset_id)
    _assert_shape(created, target, enforcement="evaluate")
    version = _latest_history_version(target)
    history_state = _history_version_state(target, version)
    _assert_shape(history_state, target, enforcement="evaluate")
    _assert_current_main(expected_main_sha)
    _assert_target_main(target_main_sha)
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
    """Require protected main to contain the reviewed non-cancellable Product workflow."""

    payload = _gh_api(
        "GET",
        f"repos/{TARGET_FULL_NAME}/contents/{PRODUCT_WORKFLOW_PATH}?ref={base_sha}",
    )
    text = _decode_workflow(payload)
    for fragment in (
        "name: Product",
        "'Product acceptance'",
        "'Product metadata-only'",
        "cancel-in-progress: false",
    ):
        if fragment not in text:
            raise RulesetGovernanceError(
                "protected-base Product workflow lacks reviewed acceptance contract"
            )


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    """Parse one GitHub ISO-8601 timestamp for ordering evidence."""

    if type(value) is not str:
        raise RulesetGovernanceError(f"{field} timestamp is missing")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RulesetGovernanceError(f"{field} timestamp is malformed") from exc


def _latest_base_retarget(pr_number: int) -> datetime:
    """Return the latest base-ref change and reject later source commits."""

    timeline = _gh_api_list(
        "GET",
        f"repos/{TARGET_FULL_NAME}/issues/{pr_number}/timeline?per_page=100",
    )
    retargets = [
        item for item in timeline
        if _plain_dict(item, field="Product canary timeline event").get("event")
        == "base_ref_changed"
    ]
    if not retargets:
        raise RulesetGovernanceError("Product canary lacks a base_ref_changed event")
    latest = max(
        _parse_timestamp(item.get("created_at"), field="base retarget")
        for item in retargets
    )
    for item in timeline:
        event = _plain_dict(item, field="Product canary timeline event")
        if event.get("event") != "committed":
            continue
        created = _parse_timestamp(event.get("created_at"), field="post-retarget commit")
        if created > latest:
            raise RulesetGovernanceError(
                "Product canary has a source commit after its base retarget"
            )
    return latest


def _canary_evidence(*, pr_number: int, run_id: int) -> tuple[str, str]:
    """Prove exact current-base Product success after a source-neutral base retarget."""

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
    _assert_target_main(base_sha)
    _assert_base_product_workflow(base_sha)

    retargeted_at = _latest_base_retarget(pr_number)
    run = _gh_api("GET", f"repos/{TARGET_FULL_NAME}/actions/runs/{run_id}")
    if (
        run.get("name") != PRODUCT_WORKFLOW_NAME
        or run.get("path") != PRODUCT_WORKFLOW_PATH
        or run.get("event") != "pull_request"
        or run.get("head_sha") != head_sha
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("run_attempt") != 1
    ):
        raise RulesetGovernanceError(
            "canary run is not exact first-attempt terminal Product success"
        )
    if _parse_timestamp(run.get("created_at"), field="Product canary run") <= retargeted_at:
        raise RulesetGovernanceError("Product canary run predates the base retarget")

    run_prs = _plain_list(run.get("pull_requests"), field="Product canary run pull_requests")
    if not any(
        _plain_dict(item, field="Product canary run pull request").get("number") == pr_number
        and _plain_dict(item, field="Product canary run pull request").get("head", {}).get("sha")
        == head_sha
        and _plain_dict(item, field="Product canary run pull request").get("base", {}).get("sha")
        == base_sha
        for item in run_prs
    ):
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
    if len(acceptance) != 1 or (
        acceptance[0].get("status") != "completed"
        or acceptance[0].get("conclusion") != "success"
    ):
        raise RulesetGovernanceError("Product acceptance canary job is not uniquely successful")
    return base_sha, head_sha


def _assert_evaluate_rule_suite(
    *,
    ruleset_id: int,
    base_sha: str,
    head_sha: str,
    not_before: datetime,
) -> None:
    """Require exact evaluate-mode workflow-rule PASS for the retarget canary."""

    suites = _gh_api_list(
        "GET",
        f"repos/{TARGET_FULL_NAME}/rulesets/rule-suites"
        f"?ref=refs/heads/{TARGET_BRANCH}&time_period=day"
        "&evaluate_status=evaluate&per_page=100",
    )
    candidates = []
    for raw in suites:
        suite = _plain_dict(raw, field="Product evaluate rule suite")
        if (
            suite.get("repository_id") == TARGET_REPOSITORY_ID
            and suite.get("ref") == f"refs/heads/{TARGET_BRANCH}"
            and suite.get("before_sha") == base_sha
            and suite.get("after_sha") == head_sha
            and _parse_timestamp(suite.get("pushed_at"), field="Product evaluate rule suite")
            > not_before
        ):
            candidates.append(suite)
    if len(candidates) != 1:
        raise RulesetGovernanceError(
            "Product canary lacks one exact current-base evaluate rule suite"
        )
    suite_id = candidates[0].get("id")
    if type(suite_id) is not int or suite_id <= 0:
        raise RulesetGovernanceError("Product evaluate rule suite identity is malformed")
    detail = _gh_api(
        "GET",
        f"repos/{TARGET_FULL_NAME}/rulesets/rule-suites/{suite_id}",
    )
    evaluations = _plain_list(
        detail.get("rule_evaluations"),
        field="Product evaluate rule evaluations",
    )
    matched = []
    for raw in evaluations:
        evaluation = _plain_dict(raw, field="Product evaluate rule evaluation")
        source = _plain_dict(evaluation.get("rule_source"), field="Product rule source")
        if (
            source.get("id") == ruleset_id
            and evaluation.get("enforcement") == "evaluate"
            and evaluation.get("rule_type") == "workflows"
            and evaluation.get("result") == "pass"
        ):
            matched.append(evaluation)
    if len(matched) != 1:
        raise RulesetGovernanceError(
            "Product workflow ruleset lacks exact evaluate-mode PASS evidence"
        )


def activate_product_ruleset(
    manifest: dict[str, Any],
    *,
    expected_main_sha: str,
    canary_pr: int,
    canary_run_id: int,
) -> str:
    """Promote evaluate to active only after exact retarget and rule-suite evidence."""

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
    _assert_shape(first, target, enforcement="evaluate")

    retargeted_at = _latest_base_retarget(canary_pr)
    base_sha, head_sha = _canary_evidence(
        pr_number=canary_pr,
        run_id=canary_run_id,
    )
    _assert_evaluate_rule_suite(
        ruleset_id=pinned_id,
        base_sha=base_sha,
        head_sha=head_sha,
        not_before=retargeted_at,
    )
    desired = _desired(enforcement="active")
    baseline_version = _latest_history_version(target)
    _assert_current_main(expected_main_sha)
    _assert_target_main(base_sha)
    second = _live(target)
    if _editable_projection(second) != _editable_projection(first):
        raise RulesetGovernanceError(
            "Product ruleset changed concurrently; refusing activation"
        )
    _assert_shape(second, target, enforcement="evaluate")
    _assert_current_main(expected_main_sha)
    _assert_target_main(base_sha)

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

    _assert_shape(after, target, enforcement="active")
    if not history_verified:
        _verify_ruleset_history_transition(
            target,
            baseline_version,
            desired,
            expected_main_sha=None,
        )
    _assert_current_main(expected_main_sha)
    _assert_target_main(base_sha)
    return "active"


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
    stage = activate_product_ruleset(
        manifest,
        expected_main_sha=args.expected_main_sha,
        canary_pr=args.canary_pr,
        canary_run_id=args.canary_run_id,
    )
    print(f"Product ruleset stage={stage}")
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
