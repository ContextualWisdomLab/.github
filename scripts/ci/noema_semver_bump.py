#!/usr/bin/env python3
"""Noema-decided semantic version bump for the central release pipeline.

Collects release evidence and requires a recorded Noema verdict fixture
(``NOEMA_SEMVER_RECORDED_RESPONSE_PATH``) for a ``major`` / ``minor`` /
``patch`` decision under semver.org 2.0.0. Fail-closes on unavailable /
low-confidence / breaking-conflict outcomes, and computes the next version
from the previous tag. Live URL/model/API-key clients are rejected until
contextual-orchestrator publishes a pinned immutable client contract
(ADR-0033). See ADR-0033.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

BUMP_VALUES = frozenset({"major", "minor", "patch"})
DEFAULT_MIN_CONFIDENCE = 0.7
CORE_SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
# Live LLM transport env vars are rejected; recorded fixtures only until CO
# publishes a pinned client/schema (gateway-token-only, orchestrator/free).
_REJECTED_LIVE_LLM_ENV = (
    "NOEMA_LLM_API_URL",
    "NOEMA_LLM_API_KEY",
    "NOEMA_LLM_MODEL",
    "CONTEXTUAL_ORCHESTRATOR_BASE_URL",
)


class SemverBumpError(RuntimeError):
    """Fail-closed release-bump failure that must stop the cut."""


@dataclass(frozen=True)
class SemverVerdict:
    """Machine-readable Noema bump verdict."""

    bump: str
    reason: str
    evidence_refs: tuple[str, ...]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """Serialize for provenance / release-notes embedding."""
        return {
            "bump": self.bump,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "confidence": self.confidence,
        }


def parse_core_semver(version: str) -> tuple[int, int, int]:
    """Parse a three-component core semver string into integers."""
    text = version.strip().lstrip("v")
    if CORE_SEMVER_RE.fullmatch(text) is None:
        raise SemverBumpError(
            f"version must be canonical three-component semver, got {version!r}"
        )
    major_s, minor_s, patch_s = text.split(".")
    return int(major_s), int(minor_s), int(patch_s)


def apply_bump(previous_version: str, bump: str) -> str:
    """Apply a semver bump class to ``previous_version``."""
    if bump not in BUMP_VALUES:
        raise SemverBumpError(f"unknown bump class {bump!r}")
    major, minor, patch = parse_core_semver(previous_version)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def load_evidence(path: Path) -> dict[str, Any]:
    """Load the release evidence pack JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemverBumpError(f"unable to read evidence pack: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemverBumpError("evidence pack must be a JSON object")
    return payload


def detected_breaking_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return evidence refs that independently imply a breaking change.

    Removed/renamed public symbols and unsourced-default removals that make
    arguments required (ADR-0028 style) are breaking. Deprecated-alias-only
    changes are intentionally excluded (they are minor).
    """
    refs: list[str] = []
    for key, prefix in (
        ("removed_public_symbols", "api:removed:"),
        ("renamed_public_symbols", "api:renamed:"),
        ("required_arg_promotions", "api:required-arg:"),
    ):
        values = evidence.get(key) or []
        if not isinstance(values, list):
            raise SemverBumpError(f"evidence.{key} must be a list")
        for item in values:
            if not isinstance(item, str) or not item.strip():
                raise SemverBumpError(f"evidence.{key} entries must be non-empty strings")
            refs.append(f"{prefix}{item.strip()}")
    return tuple(refs)


def parse_verdict(payload: Mapping[str, Any]) -> SemverVerdict:
    """Validate and normalize a Noema bump verdict object."""
    bump = payload.get("bump")
    reason = payload.get("reason")
    evidence_refs = payload.get("evidence_refs")
    confidence = payload.get("confidence")
    if bump not in BUMP_VALUES:
        raise SemverBumpError(f"verdict.bump must be one of {sorted(BUMP_VALUES)}")
    if not isinstance(reason, str) or not reason.strip():
        raise SemverBumpError("verdict.reason must be a non-empty string")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise SemverBumpError("verdict.evidence_refs must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in evidence_refs):
        raise SemverBumpError("verdict.evidence_refs entries must be non-empty strings")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise SemverBumpError("verdict.confidence must be a number")
    conf = float(confidence)
    if conf < 0.0 or conf > 1.0:
        raise SemverBumpError("verdict.confidence must be in [0, 1]")
    return SemverVerdict(
        bump=str(bump),
        reason=reason.strip(),
        evidence_refs=tuple(item.strip() for item in evidence_refs),
        confidence=conf,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model text; fail closed otherwise."""
    if not isinstance(text, str) or not text.strip():
        raise SemverBumpError("Noema returned empty content")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise SemverBumpError("Noema response did not contain a JSON object")


def load_recorded_verdict(path: Path) -> SemverVerdict:
    """Load a recorded Noema verdict fixture (tests / offline fail-open never)."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemverBumpError(f"recorded Noema verdict unavailable: {exc}") from exc
    if not isinstance(payload, dict):
        raise SemverBumpError("recorded Noema verdict must be a JSON object")
    status = payload.get("status")
    if status == "unavailable":
        raise SemverBumpError("Noema unavailable (recorded fixture)")
    if "verdict" in payload:
        inner = payload["verdict"]
        if not isinstance(inner, dict):
            raise SemverBumpError("recorded fixture verdict must be an object")
        return parse_verdict(inner)
    return parse_verdict(payload)


def _reject_live_llm_transport() -> None:
    """Fail closed when a raw LLM client env is present without a CO pin."""
    present = [
        name
        for name in _REJECTED_LIVE_LLM_ENV
        if (os.environ.get(name) or "").strip()
    ]
    if present:
        raise SemverBumpError(
            "Noema unavailable: live LLM transport env "
            f"({', '.join(present)}) is rejected until contextual-orchestrator "
            "publishes a pinned immutable client/schema; use "
            "NOEMA_SEMVER_RECORDED_RESPONSE_PATH only"
        )


def call_noema_for_bump(evidence: Mapping[str, Any]) -> SemverVerdict:
    """Load a recorded Noema bump verdict; reject live URL/key/model clients.

    ``evidence`` is accepted for API stability with callers that already pass
    the pack; live model prompting is intentionally not implemented here.
    """
    del evidence  # recorded fixtures are self-contained; pack is enforced later
    _reject_live_llm_transport()
    recorded = (os.environ.get("NOEMA_SEMVER_RECORDED_RESPONSE_PATH") or "").strip()
    if recorded:
        return load_recorded_verdict(Path(recorded))
    raise SemverBumpError(
        "Noema unavailable: set NOEMA_SEMVER_RECORDED_RESPONSE_PATH; "
        "live URL/model/API-key clients are fail-closed until "
        "contextual-orchestrator publishes a pinned immutable client/schema"
    )


def enforce_fail_closed(
    verdict: SemverVerdict,
    evidence: Mapping[str, Any],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> None:
    """Stop the release on low confidence or under-bump of breaking changes."""
    if verdict.confidence < min_confidence:
        raise SemverBumpError(
            f"Noema confidence {verdict.confidence} below minimum {min_confidence}; "
            "human decision required"
        )
    breaking = detected_breaking_refs(evidence)
    if breaking and verdict.bump == "patch":
        raise SemverBumpError(
            "Noema verdict conflicts with detected breaking change "
            f"(bump=patch but breaking refs={list(breaking)}); human decision required"
        )
    if breaking and verdict.bump == "minor":
        # Renames/required-arg promotions are major; minor under-bumps them.
        raise SemverBumpError(
            "Noema verdict conflicts with detected breaking change "
            f"(bump=minor but breaking refs={list(breaking)}); human decision required"
        )


def decide_release_version(
    evidence: Mapping[str, Any],
    *,
    previous_version: str | None = None,
    requested_version: str | None = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Return provenance including bump verdict and computed release version."""
    prev = previous_version or evidence.get("previous_version")
    if not isinstance(prev, str) or not prev.strip():
        raise SemverBumpError("previous_version is required in evidence or arguments")
    prev = prev.strip().lstrip("v")
    parse_core_semver(prev)

    verdict = call_noema_for_bump(evidence)
    enforce_fail_closed(verdict, evidence, min_confidence=min_confidence)
    computed = apply_bump(prev, verdict.bump)

    if requested_version:
        requested = requested_version.strip().lstrip("v")
        parse_core_semver(requested)
        if requested != computed:
            raise SemverBumpError(
                f"requested release_version {requested} does not match "
                f"Noema bump {verdict.bump} from {prev} (= {computed}); "
                "human decision required"
            )

    return {
        "previous_version": prev,
        "release_version": computed,
        "verdict": verdict.to_dict(),
        "breaking_refs_detected": list(detected_breaking_refs(evidence)),
        "min_confidence": min_confidence,
    }


def render_notes_prefix(provenance: Mapping[str, Any]) -> str:
    """Markdown block quoting the Noema verdict for release notes."""
    verdict = provenance["verdict"]
    refs = ", ".join(f"`{item}`" for item in verdict["evidence_refs"])
    return (
        "### Noema semver verdict\n\n"
        f"- Bump: `{verdict['bump']}` "
        f"(from `{provenance['previous_version']}` → "
        f"`{provenance['release_version']}`)\n"
        f"- Confidence: `{verdict['confidence']}`\n"
        f"- Reason: {verdict['reason']}\n"
        f"- Evidence refs: {refs}\n"
    )


def build_parser() -> argparse.ArgumentParser:
    """CLI parser for the release-tag workflow step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Path to the evidence pack JSON",
    )
    parser.add_argument(
        "--previous-version",
        default="",
        help="Override evidence.previous_version",
    )
    parser.add_argument(
        "--requested-version",
        default="",
        help="Optional human-requested version that must match the Noema bump",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help="Fail closed below this confidence",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write provenance JSON here",
    )
    parser.add_argument(
        "--notes-prefix",
        type=Path,
        help="Optional path for the release-notes Noema quote block",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional GitHub Actions output file to append release_version",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point used by the reusable release-tag workflow."""
    parser = build_parser()
    args = parser.parse_args(argv)
    evidence = load_evidence(args.evidence)
    try:
        provenance = decide_release_version(
            evidence,
            previous_version=args.previous_version or None,
            requested_version=args.requested_version or None,
            min_confidence=args.min_confidence,
        )
    except SemverBumpError as exc:
        print(f"::error::Noema semver gate failed: {exc}", file=sys.stderr)
        return 1

    args.output.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.notes_prefix is not None:
        args.notes_prefix.write_text(render_notes_prefix(provenance), encoding="utf-8")
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"release_version={provenance['release_version']}\n")
            handle.write(f"bump={provenance['verdict']['bump']}\n")
    print(json.dumps(provenance, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
