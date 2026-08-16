"""Decide how central review should measure a Rust workspace.

OriginWeave-class repos declare ``rust-version = "1.97"`` and ship
``scripts/ci/verify_coverage.py`` instead of
``workspace.metadata.opencode.coverage.minimum_lines``. Applying the
central default ``--fail-under-lines 100`` on Debian ``rustc`` is a
false blocker; this module prefers the repo verifier when that file
exists.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from rust_coverage_threshold import read_minimum_lines
except ImportError:  # pragma: no cover - package-style import in CI
    from scripts.ci.rust_coverage_threshold import read_minimum_lines


@dataclass(frozen=True)
class CoveragePlan:
    """How the coverage-evidence job should score a Rust workspace."""

    mode: str
    fail_under: int | None
    verifier: Path | None


def _parse_manifest(manifest: Path) -> dict[str, Any]:
    """Return the Cargo.toml mapping or raise ``ValueError``."""
    try:
        parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid Cargo.toml: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Cargo.toml root must be a table")
    return parsed


def _opencode_coverage_metadata(parsed: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return package or workspace ``metadata.opencode.coverage`` when present."""
    for root_key in ("package", "workspace"):
        root = parsed.get(root_key)
        if not isinstance(root, dict):
            continue
        metadata = root.get("metadata")
        if not isinstance(metadata, dict):
            continue
        opencode = metadata.get("opencode")
        if not isinstance(opencode, dict):
            continue
        coverage = opencode.get("coverage")
        if isinstance(coverage, dict):
            return coverage
    return None


def repo_coverage_verifier(repo_root: Path) -> Path | None:
    """Return the repo's coverage verifier script when it exists as a file."""
    for relative in (
        Path("scripts") / "ci" / "verify_coverage.py",
        Path("scripts") / "ci" / "verify_coverage.sh",
    ):
        candidate = repo_root / relative
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def coverage_plan(*, repo_root: Path, manifest: Path) -> CoveragePlan:
    """Choose llvm-cov threshold vs the repo's own coverage verifier.

    Repos that publish ``workspace.metadata.opencode.coverage`` keep the
    central ``cargo llvm-cov --fail-under-lines`` path. Repos that ship
    ``scripts/ci/verify_coverage.py`` (or ``.sh``) without that metadata
    must not inherit the canned 100% default. Only a workspace with
    neither metadata nor a verifier still defaults to 100.
    """
    parsed = _parse_manifest(manifest)
    metadata = _opencode_coverage_metadata(parsed)
    if metadata is not None:
        threshold = read_minimum_lines(manifest)
        fail_under = 100 if threshold is None else int(threshold)
        return CoveragePlan(
            mode="llvm-cov-threshold",
            fail_under=fail_under,
            verifier=None,
        )
    verifier = repo_coverage_verifier(repo_root)
    if verifier is not None:
        return CoveragePlan(mode="repo-verifier", fail_under=None, verifier=verifier)
    return CoveragePlan(mode="llvm-cov-threshold", fail_under=100, verifier=None)


def rustc_cargo_version_log(*, rustc: str, cargo: str, rustup_show: str = "") -> str:
    """Format rustc/cargo identity for the coverage_summary artifact."""
    lines = [
        f"rustc: {rustc.strip() or 'unavailable'}",
        f"cargo: {cargo.strip() or 'unavailable'}",
    ]
    show = rustup_show.strip()
    if show:
        lines.append(f"rustup show: {show}")
    return "\n".join(lines) + "\n"


def plan_fields(plan: CoveragePlan) -> str:
    """Serialize one coverage plan as tab-separated mode, threshold, verifier."""
    fail_under = "" if plan.fail_under is None else str(plan.fail_under)
    verifier = "" if plan.verifier is None else plan.verifier.as_posix()
    return f"{plan.mode}\t{fail_under}\t{verifier}\n"


def main(argv: list[str] | None = None) -> int:
    """Print the coverage plan for one Cargo manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = coverage_plan(repo_root=args.repo_root, manifest=args.manifest)
    except (OSError, ValueError) as exc:
        print(f"invalid Rust coverage policy: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(plan_fields(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
