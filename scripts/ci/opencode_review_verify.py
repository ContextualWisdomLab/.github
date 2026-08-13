"""Validate and normalize non-publishing OpenCode shadow-review evidence."""

from __future__ import annotations

import argparse
import re
import runpy
import sys
from pathlib import Path
from typing import Any, Sequence

_PRIMITIVES = runpy.run_path(
    str(Path(__file__).with_name("opencode_review_shadow_primitives.py"))
)
atomic_write_json = _PRIMITIVES["atomic_write_json"]
digest_json = _PRIMITIVES["digest_json"]
require_commit = _PRIMITIVES["require_commit"]
require_fields = _PRIMITIVES["require_fields"]
require_integer = _PRIMITIVES["require_integer"]
require_object = _PRIMITIVES["require_object"]
require_relative_path = _PRIMITIVES["require_relative_path"]
require_sha256 = _PRIMITIVES["require_sha256"]
require_string = _PRIMITIVES["require_string"]
strict_load_json = _PRIMITIVES["strict_load_json"]

ROOT_FIELDS = {
    "schema_version", "verification_id", "repository", "pull_request_number", "base_sha",
    "head_sha", "evidence_sha256", "risk_tier", "verification_policy", "source_index",
    "detector_attempts", "verifier_attempts", "candidates", "verifier_decisions",
}
POLICY_FIELDS = {"shadow_mode", "publication_enabled", "minimum_independent_verifiers", "require_model_diversity"}
SOURCE_FIELDS = {"path", "line", "source_line_sha256", "relationship"}
ATTEMPT_FIELDS = {"attempt_id", "phase", "role_code", "provider_id", "model_id", "reviewed_head_sha", "status", "output_sha256"}
CANDIDATE_FIELDS = {
    "candidate_id", "detector_attempt_id", "reviewed_head_sha", "infrastructure_only",
    "path", "line", "source_line_sha256", "defect_class", "severity", "blocking",
    "trigger", "impact", "root_cause", "fix_direction", "regression_target",
}
DECISION_FIELDS = {"candidate_id", "verifier_attempt_id", "outcome", "reason", "source_line_sha256"}


class VerificationValidationError(ValueError):
    """Raised when a verification bundle violates its strict evidence contract."""


def validation_error_type() -> type[VerificationValidationError]:
    """Return the public validation error used by strict JSON loading."""
    return VerificationValidationError


def load_json(path: Path) -> Any:
    """Load one strict verification JSON file."""
    return strict_load_json(path, VerificationValidationError)


def _list(value: Any, label: str) -> list[Any]:
    """Validate a JSON array without silently coercing other iterables."""
    if not isinstance(value, list):
        raise VerificationValidationError(f"{label} must be a list")
    return value


def _validate_bundle(raw: Any) -> dict[str, Any]:
    """Validate all exact-head identity and evidence references in a bundle."""
    value = require_object(raw, "verification bundle", VerificationValidationError)
    require_fields(value, ROOT_FIELDS, "verification bundle", VerificationValidationError)
    if value["schema_version"] != "1.0":
        raise VerificationValidationError("unsupported schema_version")
    require_string(value["verification_id"], "verification_id", VerificationValidationError)
    require_string(value["repository"], "repository", VerificationValidationError)
    require_integer(value["pull_request_number"], "pull_request_number", VerificationValidationError, minimum=1)
    require_commit(value["base_sha"], "base_sha", VerificationValidationError)
    head = require_commit(value["head_sha"], "head_sha commit SHA", VerificationValidationError)
    require_sha256(value["evidence_sha256"], "evidence_sha256", VerificationValidationError)
    if value["risk_tier"] not in {"low", "standard", "high", "critical"}:
        raise VerificationValidationError("risk_tier is unsupported")
    policy = require_object(value["verification_policy"], "verification_policy", VerificationValidationError)
    require_fields(policy, POLICY_FIELDS, "verification_policy", VerificationValidationError)
    if policy["shadow_mode"] is not True:
        raise VerificationValidationError("shadow_mode must be true")
    if policy["publication_enabled"] is not False:
        raise VerificationValidationError("publication_enabled must be false")
    require_integer(policy["minimum_independent_verifiers"], "minimum_independent_verifiers integer", VerificationValidationError, minimum=1)
    if not isinstance(policy["require_model_diversity"], bool):
        raise VerificationValidationError("require_model_diversity must be boolean")

    source_identities: set[tuple[str, int]] = set()
    for index, raw_source in enumerate(_list(value["source_index"], "source_index")):
        source = require_object(raw_source, f"source_index[{index}]", VerificationValidationError)
        require_fields(source, SOURCE_FIELDS, f"source_index[{index}]", VerificationValidationError)
        path = require_relative_path(source["path"], "source path", VerificationValidationError)
        line = require_integer(source["line"], "source line integer", VerificationValidationError, minimum=1)
        require_sha256(source["source_line_sha256"], "source_line_sha256", VerificationValidationError)
        if source["relationship"] not in {"changed", "connected"}:
            raise VerificationValidationError("source relationship is unsupported")
        identity = (path, line)
        if identity in source_identities:
            raise VerificationValidationError("source identity must be unique")
        source_identities.add(identity)

    attempt_ids: set[str] = set()
    attempts: dict[str, dict[str, Any]] = {}
    for collection, expected_phase in (("detector_attempts", "detector"), ("verifier_attempts", "verifier")):
        for index, raw_attempt in enumerate(_list(value[collection], collection)):
            attempt = require_object(raw_attempt, f"{collection}[{index}]", VerificationValidationError)
            require_fields(attempt, ATTEMPT_FIELDS, f"{collection}[{index}]", VerificationValidationError)
            attempt_id = require_string(attempt["attempt_id"], "attempt_id", VerificationValidationError)
            if attempt_id in attempt_ids:
                raise VerificationValidationError("attempt_id must be unique")
            attempt_ids.add(attempt_id)
            if attempt["phase"] != expected_phase:
                raise VerificationValidationError("attempt phase does not match collection")
            for field in ("role_code", "provider_id", "model_id"):
                require_string(attempt[field], field, VerificationValidationError)
            if attempt["reviewed_head_sha"] != head:
                raise VerificationValidationError("reviewed_head_sha must match head_sha")
            if attempt["status"] not in {"complete", "failed", "timed_out", "dependency_failed"}:
                raise VerificationValidationError("attempt status is unsupported")
            require_sha256(attempt["output_sha256"], "output_sha256", VerificationValidationError)
            attempts[attempt_id] = attempt

    candidate_ids: set[str] = set()
    for index, raw_candidate in enumerate(_list(value["candidates"], "candidates")):
        candidate_value = require_object(raw_candidate, f"candidates[{index}]", VerificationValidationError)
        require_fields(candidate_value, CANDIDATE_FIELDS, f"candidates[{index}]", VerificationValidationError)
        candidate_id = require_string(candidate_value["candidate_id"], "candidate_id", VerificationValidationError)
        if candidate_id in candidate_ids:
            raise VerificationValidationError("candidate_id must be unique")
        candidate_ids.add(candidate_id)
        detector_id = require_string(candidate_value["detector_attempt_id"], "detector_attempt_id", VerificationValidationError)
        if detector_id not in attempts or attempts[detector_id]["phase"] != "detector":
            raise VerificationValidationError("unknown detector attempt")
        if candidate_value["reviewed_head_sha"] != head:
            raise VerificationValidationError("candidate reviewed_head_sha must match head_sha")
        if not isinstance(candidate_value["infrastructure_only"], bool) or not isinstance(candidate_value["blocking"], bool):
            raise VerificationValidationError("candidate booleans are invalid")
        require_relative_path(candidate_value["path"], "candidate path", VerificationValidationError)
        require_integer(candidate_value["line"], "candidate line integer", VerificationValidationError, minimum=1)
        require_sha256(candidate_value["source_line_sha256"], "candidate source_line_sha256", VerificationValidationError)
        for field in ("defect_class", "severity", "trigger", "impact", "root_cause", "fix_direction", "regression_target"):
            require_string(candidate_value[field], field, VerificationValidationError)

    decision_ids: set[tuple[str, str]] = set()
    for index, raw_decision in enumerate(_list(value["verifier_decisions"], "verifier_decisions")):
        decision = require_object(raw_decision, f"verifier_decisions[{index}]", VerificationValidationError)
        require_fields(decision, DECISION_FIELDS, f"verifier_decisions[{index}]", VerificationValidationError)
        candidate_id = require_string(decision["candidate_id"], "candidate_id", VerificationValidationError)
        verifier_id = require_string(decision["verifier_attempt_id"], "verifier_attempt_id", VerificationValidationError)
        if candidate_id not in candidate_ids:
            raise VerificationValidationError("verifier decision references unknown candidate")
        if verifier_id not in attempts or attempts[verifier_id]["phase"] != "verifier":
            raise VerificationValidationError("verifier decision references unknown verifier")
        identity = (candidate_id, verifier_id)
        if identity in decision_ids:
            raise VerificationValidationError("verifier decision identity must be unique")
        decision_ids.add(identity)
        if decision["outcome"] not in {"supported", "rejected"}:
            raise VerificationValidationError("verifier decision outcome is unsupported")
        require_string(decision["reason"], "verifier reason", VerificationValidationError)
        require_sha256(decision["source_line_sha256"], "decision source_line_sha256", VerificationValidationError)
    return value


def _reject(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    """Return a non-source-bearing rejection receipt."""
    return {"candidate_id": candidate["candidate_id"], "reason_code": reason}


def _normal_root(value: str) -> str:
    """Normalize semantic whitespace and case for deterministic deduplication."""
    return re.sub(r"\s+", " ", value).strip().casefold()


def verify_bundle(raw: Any) -> dict[str, Any]:
    """Verify exact-head source authority and return deterministic shadow-only findings."""
    value = _validate_bundle(raw)
    sources = {(item["path"], item["line"]): item for item in value["source_index"]}
    detectors = {item["attempt_id"]: item for item in value["detector_attempts"]}
    verifiers = {item["attempt_id"]: item for item in value["verifier_attempts"]}
    decisions: dict[str, list[dict[str, Any]]] = {}
    for decision in value["verifier_decisions"]:
        decisions.setdefault(decision["candidate_id"], []).append(decision)
    metrics = {
        "candidate_count": len(value["candidates"]), "accepted_finding_count": 0,
        "rejected_candidate_count": 0, "duplicate_candidate_count": 0,
        "infrastructure_only_candidate_count": 0, "unsupported_candidate_count": 0,
        "source_contract_failure_count": 0, "insufficient_verifier_count": 0,
    }
    rejected: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for candidate_value in sorted(value["candidates"], key=lambda item: item["candidate_id"]):
        if candidate_value["infrastructure_only"]:
            reason = "infrastructure_only"
            metrics["infrastructure_only_candidate_count"] += 1
        elif detectors[candidate_value["detector_attempt_id"]]["status"] != "complete":
            reason = "detector_not_complete"
        else:
            source = sources.get((candidate_value["path"], candidate_value["line"]))
            if source is None or source["source_line_sha256"] != candidate_value["source_line_sha256"]:
                reason = "source_receipt_mismatch"
                metrics["source_contract_failure_count"] += 1
            else:
                candidate_decisions = decisions.get(candidate_value["candidate_id"], [])
                supported = [
                    item for item in candidate_decisions
                    if item["outcome"] == "supported"
                    and item["source_line_sha256"] == candidate_value["source_line_sha256"]
                    and verifiers[item["verifier_attempt_id"]]["status"] == "complete"
                ]
                if candidate_decisions and not any(item["outcome"] == "supported" for item in candidate_decisions):
                    reason = "unsupported"
                    metrics["unsupported_candidate_count"] += 1
                else:
                    verifier_models = {verifiers[item["verifier_attempt_id"]]["model_id"] for item in supported}
                    detector_model = detectors[candidate_value["detector_attempt_id"]]["model_id"]
                    required = value["verification_policy"]["minimum_independent_verifiers"]
                    diverse = not value["verification_policy"]["require_model_diversity"] or detector_model not in verifier_models
                    if len(verifier_models) < required or not diverse:
                        reason = "insufficient_verifier_evidence"
                        metrics["insufficient_verifier_count"] += 1
                    else:
                        finding = {
                            key: candidate_value[key] for key in (
                                "path", "line", "source_line_sha256", "defect_class", "severity",
                                "blocking", "trigger", "impact", "root_cause", "fix_direction", "regression_target",
                            )
                        }
                        finding["detector_attempt_ids"] = [candidate_value["detector_attempt_id"]]
                        finding["verifier_attempt_ids"] = sorted(item["verifier_attempt_id"] for item in supported)
                        finding["finding_fingerprint"] = digest_json({
                            "path": finding["path"], "line": finding["line"],
                            "root_cause": _normal_root(finding["root_cause"]),
                        })
                        accepted.append(finding)
                        continue
        rejected.append(_reject(candidate_value, reason))
    grouped: dict[tuple[str, int, str], dict[str, Any]] = {}
    for finding in accepted:
        identity = (finding["path"], finding["line"], _normal_root(finding["root_cause"]))
        if identity in grouped:
            existing = grouped[identity]
            existing["detector_attempt_ids"] = sorted(set(existing["detector_attempt_ids"] + finding["detector_attempt_ids"]))
            existing["verifier_attempt_ids"] = sorted(set(existing["verifier_attempt_ids"] + finding["verifier_attempt_ids"]))
            metrics["duplicate_candidate_count"] += 1
        else:
            grouped[identity] = finding
    findings = sorted(grouped.values(), key=lambda item: (item["path"], item["line"], item["finding_fingerprint"]))
    metrics["accepted_finding_count"] = len(findings)
    metrics["rejected_candidate_count"] = len(rejected)
    report: dict[str, Any] = {
        "schema_version": "1.0", "verification_id": value["verification_id"],
        "repository": value["repository"], "pull_request_number": value["pull_request_number"],
        "base_sha": value["base_sha"], "head_sha": value["head_sha"],
        "evidence_sha256": value["evidence_sha256"], "risk_tier": value["risk_tier"],
        "shadow_mode": True, "publication_enabled": False,
        "shadow_findings": findings, "published_findings": [],
        "rejected_candidates": sorted(rejected, key=lambda item: item["candidate_id"]),
        "metrics": metrics,
    }
    report["verification_sha256"] = digest_json(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline verifier CLI and return a stable process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        atomic_write_json(arguments.output, verify_bundle(load_json(arguments.input)))
    except (VerificationValidationError, OSError) as error:
        print(f"shadow verification rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
