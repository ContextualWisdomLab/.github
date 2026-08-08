#!/usr/bin/env python3
"""Deterministically select exact-head cases for review-quality annotation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

VALID_BUCKETS = {"small", "medium", "large"}
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class CorpusSamplingError(ValueError):
    """Signal malformed or internally inconsistent corpus inventory evidence."""


class InsufficientCorpusError(CorpusSamplingError):
    """Signal a valid inventory that cannot satisfy its hard sampling policy."""


def reject(message: str) -> None:
    """Raise one stable corpus validation error."""
    raise CorpusSamplingError(message)


def require_exact_fields(
    value: Mapping[str, Any], path: str, allowed_fields: set[str]
) -> None:
    """Reject unreviewed extension fields at one governed schema layer."""
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        reject(f"{path} has unknown fields: {', '.join(unknown)}")


def object_value(value: Any, path: str) -> Mapping[str, Any]:
    """Return a JSON object or reject a shape mismatch."""
    if not isinstance(value, Mapping):
        reject(f"{path} must be an object")
    return value


def array_value(value: Any, path: str) -> list[Any]:
    """Return a JSON array or reject a shape mismatch."""
    if not isinstance(value, list):
        reject(f"{path} must be an array")
    return value


def text_value(value: Any, path: str) -> str:
    """Return stripped non-empty text or reject it."""
    if not isinstance(value, str) or not value.strip():
        reject(f"{path} must be non-empty text")
    return value.strip()


def bool_value(value: Any, path: str) -> bool:
    """Return an actual Boolean rather than an integer lookalike."""
    if not isinstance(value, bool):
        reject(f"{path} must be boolean")
    return value


def count_value(value: Any, path: str, *, positive: bool = False) -> int:
    """Return a non-negative or positive integer count."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        reject(f"{path} must be a non-negative integer")
    if positive and value == 0:
        reject(f"{path} must be a positive integer")
    return value


def normalized_unique_texts(value: Any, path: str) -> list[str]:
    """Return case-folded unique text values while preserving declaration order."""
    output: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(array_value(value, path)):
        normalized = text_value(item, f"{path}[{index}]").casefold()
        if normalized in seen:
            reject(f"{path} duplicates {normalized!r}")
        seen.add(normalized)
        output.append(normalized)
    if not output:
        reject(f"{path} must not be empty")
    return output


def commit_sha_value(value: Any, path: str) -> str:
    """Return one lowercase full commit SHA."""
    result = text_value(value, path)
    if not COMMIT_SHA_RE.fullmatch(result):
        reject(f"{path} must be a 40-character lowercase commit SHA")
    return result


def digest_value(value: Any, path: str) -> str:
    """Return one canonical SHA-256 evidence digest."""
    result = text_value(value, path)
    if not DIGEST_RE.fullmatch(result):
        reject(f"{path} must use sha256:<64 lowercase hex characters>")
    return result


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for content-addressed evidence receipts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """Return a canonical SHA-256 digest for a JSON-compatible value."""
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_inventory(raw_value: Any) -> dict[str, Any]:
    """Validate and normalize one offline exact-head candidate inventory."""
    value = object_value(raw_value, "inventory")
    require_exact_fields(
        value,
        "inventory",
        {"schema_version", "inventory_id", "generated_at", "sampling_policy", "candidates"},
    )
    if value.get("schema_version") != "1.0":
        reject("inventory.schema_version must equal '1.0'")
    inventory_id = text_value(value.get("inventory_id"), "inventory.inventory_id")
    generated_at = text_value(value.get("generated_at"), "inventory.generated_at")
    if not TIMESTAMP_RE.fullmatch(generated_at):
        reject("inventory.generated_at must use UTC YYYY-MM-DDTHH:MM:SSZ")

    raw_policy = object_value(value.get("sampling_policy"), "sampling_policy")
    require_exact_fields(
        raw_policy,
        "sampling_policy",
        {
            "sample_size",
            "minimum_primary_languages",
            "required_diff_size_buckets",
            "required_risk_classes",
            "required_defect_classes",
        },
    )
    policy = {
        "sample_size": count_value(
            raw_policy.get("sample_size"), "sampling_policy.sample_size", positive=True
        ),
        "minimum_primary_languages": count_value(
            raw_policy.get("minimum_primary_languages"),
            "sampling_policy.minimum_primary_languages",
            positive=True,
        ),
        "required_diff_size_buckets": normalized_unique_texts(
            raw_policy.get("required_diff_size_buckets"),
            "sampling_policy.required_diff_size_buckets",
        ),
        "required_risk_classes": normalized_unique_texts(
            raw_policy.get("required_risk_classes"),
            "sampling_policy.required_risk_classes",
        ),
        "required_defect_classes": normalized_unique_texts(
            raw_policy.get("required_defect_classes"),
            "sampling_policy.required_defect_classes",
        ),
    }
    invalid_buckets = set(policy["required_diff_size_buckets"]) - VALID_BUCKETS
    if invalid_buckets:
        reject("sampling_policy.required_diff_size_buckets contains invalid values")
    if policy["minimum_primary_languages"] > policy["sample_size"]:
        reject("sampling_policy.minimum_primary_languages exceeds sample_size")

    candidate_fields = {
        "case_id",
        "repository",
        "pull_request_number",
        "base_sha",
        "head_sha",
        "diff_sha256",
        "context_sha256",
        "primary_language",
        "diff_size_bucket",
        "risk_class",
        "defect_class_targets",
        "changed_files",
        "additions",
        "deletions",
        "full_repository_context_available",
        "same_head_review_possible",
        "independent_expert_capacity_confirmed",
    }
    candidates: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    seen_heads: set[tuple[str, int, str]] = set()
    for index, raw_candidate in enumerate(array_value(value.get("candidates"), "candidates")):
        path = f"candidates[{index}]"
        candidate_value = object_value(raw_candidate, path)
        require_exact_fields(candidate_value, path, candidate_fields)
        case_id = text_value(candidate_value.get("case_id"), f"{path}.case_id")
        if case_id in seen_cases:
            reject(f"{path}.case_id duplicates {case_id!r}")
        seen_cases.add(case_id)
        repository = text_value(candidate_value.get("repository"), f"{path}.repository")
        if not REPOSITORY_RE.fullmatch(repository):
            reject(f"{path}.repository must use owner/name")
        pull_request_number = count_value(
            candidate_value.get("pull_request_number"),
            f"{path}.pull_request_number",
            positive=True,
        )
        head_sha = commit_sha_value(candidate_value.get("head_sha"), f"{path}.head_sha")
        exact_identity = (repository.casefold(), pull_request_number, head_sha)
        if exact_identity in seen_heads:
            reject(f"{path} duplicates an exact-head identity")
        seen_heads.add(exact_identity)
        bucket = text_value(
            candidate_value.get("diff_size_bucket"), f"{path}.diff_size_bucket"
        ).casefold()
        if bucket not in VALID_BUCKETS:
            reject(f"{path}.diff_size_bucket is invalid")
        candidate = {
            "case_id": case_id,
            "repository": repository,
            "pull_request_number": pull_request_number,
            "base_sha": commit_sha_value(
                candidate_value.get("base_sha"), f"{path}.base_sha"
            ),
            "head_sha": head_sha,
            "diff_sha256": digest_value(
                candidate_value.get("diff_sha256"), f"{path}.diff_sha256"
            ),
            "context_sha256": digest_value(
                candidate_value.get("context_sha256"), f"{path}.context_sha256"
            ),
            "primary_language": text_value(
                candidate_value.get("primary_language"), f"{path}.primary_language"
            ).casefold(),
            "diff_size_bucket": bucket,
            "risk_class": text_value(
                candidate_value.get("risk_class"), f"{path}.risk_class"
            ).casefold(),
            "defect_class_targets": normalized_unique_texts(
                candidate_value.get("defect_class_targets"),
                f"{path}.defect_class_targets",
            ),
            "changed_files": count_value(
                candidate_value.get("changed_files"), f"{path}.changed_files", positive=True
            ),
            "additions": count_value(
                candidate_value.get("additions"), f"{path}.additions"
            ),
            "deletions": count_value(
                candidate_value.get("deletions"), f"{path}.deletions"
            ),
            "full_repository_context_available": bool_value(
                candidate_value.get("full_repository_context_available"),
                f"{path}.full_repository_context_available",
            ),
            "same_head_review_possible": bool_value(
                candidate_value.get("same_head_review_possible"),
                f"{path}.same_head_review_possible",
            ),
            "independent_expert_capacity_confirmed": bool_value(
                candidate_value.get("independent_expert_capacity_confirmed"),
                f"{path}.independent_expert_capacity_confirmed",
            ),
        }
        candidates.append(candidate)
    if not candidates:
        reject("candidates must not be empty")
    return {
        "schema_version": "1.0",
        "inventory_id": inventory_id,
        "generated_at": generated_at,
        "sampling_policy": policy,
        "candidates": candidates,
    }


def candidate_priority(candidate: Mapping[str, Any], seed: str) -> str:
    """Return a deterministic seed-bound ordering key for one candidate."""
    payload = "\0".join((seed, candidate["case_id"], candidate["head_sha"]))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def coverage_tokens(candidate: Mapping[str, Any]) -> set[str]:
    """Return hard policy dimensions satisfied by one candidate."""
    tokens = {
        f"bucket:{candidate['diff_size_bucket']}",
        f"risk:{candidate['risk_class']}",
    }
    tokens.update(f"defect:{item}" for item in candidate["defect_class_targets"])
    return tokens


def sample_inventory(raw_value: Any, *, seed: str) -> dict[str, Any]:
    """Select a deterministic policy-complete sample from one valid inventory."""
    normalized_seed = text_value(seed, "seed")
    inventory = validate_inventory(raw_value)
    policy = inventory["sampling_policy"]
    eligible = [
        item
        for item in inventory["candidates"]
        if item["full_repository_context_available"]
        and item["same_head_review_possible"]
        and item["independent_expert_capacity_confirmed"]
    ]
    if len(eligible) < policy["sample_size"]:
        raise InsufficientCorpusError(
            "eligible candidate count is below sampling_policy.sample_size"
        )

    available_languages = {item["primary_language"] for item in eligible}
    if len(available_languages) < policy["minimum_primary_languages"]:
        raise InsufficientCorpusError(
            "eligible inventory cannot satisfy minimum_primary_languages"
        )

    required = {
        *(f"bucket:{item}" for item in policy["required_diff_size_buckets"]),
        *(f"risk:{item}" for item in policy["required_risk_classes"]),
        *(f"defect:{item}" for item in policy["required_defect_classes"]),
    }
    available = set().union(*(coverage_tokens(item) for item in eligible))
    missing = sorted(required - available)
    if missing:
        raise InsufficientCorpusError(
            f"eligible inventory lacks required coverage: {', '.join(missing)}"
        )

    priorities = {item["case_id"]: candidate_priority(item, normalized_seed) for item in eligible}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    uncovered = set(required)
    languages: set[str] = set()
    minimum_languages = policy["minimum_primary_languages"]
    while uncovered or len(languages) < minimum_languages:
        ranked = sorted(
            (item for item in eligible if item["case_id"] not in selected_ids),
            key=lambda item: (
                -(
                    len(coverage_tokens(item) & uncovered)
                    + int(
                        len(languages) < minimum_languages
                        and item["primary_language"] not in languages
                    )
                ),
                -int(
                    len(languages) < minimum_languages
                    and item["primary_language"] not in languages
                ),
                -len(coverage_tokens(item) & uncovered),
                priorities[item["case_id"]],
                item["case_id"],
            ),
        )
        choice = ranked[0]
        hard_gain = coverage_tokens(choice) & uncovered
        language_gain = (
            len(languages) < minimum_languages
            and choice["primary_language"] not in languages
        )
        selected.append(choice)
        selected_ids.add(choice["case_id"])
        uncovered -= hard_gain
        languages.add(choice["primary_language"])
        if len(selected) > policy["sample_size"]:
            raise InsufficientCorpusError(
                "sampling_policy.sample_size is too small for required coverage and language policy"
            )

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        if item["case_id"] not in selected_ids:
            key = (
                item["primary_language"],
                item["diff_size_bucket"],
                item["risk_class"],
            )
            groups[key].append(item)
    for values in groups.values():
        values.sort(key=lambda item: (priorities[item["case_id"]], item["case_id"]))
    group_order = sorted(
        groups,
        key=lambda key: hashlib.sha256(
            f"{normalized_seed}\0{'|'.join(key)}".encode("utf-8")
        ).hexdigest(),
    )
    fill_candidates = sorted(
        (
            (item_position, group_position, item)
            for group_position, key in enumerate(group_order)
            for item_position, item in enumerate(groups[key])
        ),
        key=lambda entry: (entry[0], entry[1]),
    )
    needed = policy["sample_size"] - len(selected)
    selected.extend(item for _, _, item in fill_candidates[:needed])

    selected.sort(key=lambda item: item["case_id"])
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for item in selected:
        counts[(item["primary_language"], item["diff_size_bucket"], item["risk_class"])] += 1
    stratum_counts = [
        {
            "primary_language": key[0],
            "diff_size_bucket": key[1],
            "risk_class": key[2],
            "case_count": count,
        }
        for key, count in sorted(counts.items())
    ]
    report_without_digest = {
        "schema_version": "1.0",
        "sample_id": f"{inventory['inventory_id']}__{content_digest(normalized_seed)[7:19]}",
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_sha256": content_digest(inventory),
        "selection_seed": normalized_seed,
        "sample_size": len(selected),
        "eligible_candidate_count": len(eligible),
        "excluded_candidate_count": len(inventory["candidates"]) - len(eligible),
        "sampling_policy": policy,
        "stratum_counts": stratum_counts,
        "selected_cases": selected,
    }
    return {
        **report_without_digest,
        "selection_sha256": content_digest(report_without_digest),
    }


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate member names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            reject(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    """Reject non-finite constants accepted by Python's permissive JSON parser."""
    reject(f"non-finite JSON number: {value}")


def load_json(path: Path) -> Any:
    """Load strict UTF-8 JSON with bounded stable validation errors."""
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=strict_pairs,
            parse_constant=reject_constant,
        )
    except (OSError, json.JSONDecodeError) as error:
        reject(f"cannot load corpus inventory: {error}")


def write_text(path: Path, content: str) -> None:
    """Atomically replace one UTF-8 output after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sampler CLI and return stable malformed/insufficient statuses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="opencode-review-corpus-v1")
    arguments = parser.parse_args(argv)
    try:
        report = sample_inventory(load_json(arguments.input), seed=arguments.seed)
    except InsufficientCorpusError as error:
        print(f"corpus inventory insufficient: {error}", file=sys.stderr)
        return 3
    except CorpusSamplingError as error:
        print(f"corpus inventory rejected: {error}", file=sys.stderr)
        return 2
    write_text(
        arguments.output,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
