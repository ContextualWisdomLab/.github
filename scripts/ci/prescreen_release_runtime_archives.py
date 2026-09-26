#!/usr/bin/env python3
"""Prescreen exact transported runtime wheels before Strix credentials exist."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.ci import release_dependency_gate as gate
    from scripts.ci.verify_release_distribution_set import _json_bytes
except ImportError:  # pragma: no cover - trusted direct `python3 -I` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import release_dependency_gate as gate
    from verify_release_distribution_set import _json_bytes


def prescreen(scope: Any, root: Path) -> list[dict[str, Any]]:
    """Rebind every wheel byte and apply the existing licence decision path."""
    if (not isinstance(scope, Mapping)
            or not isinstance(scope.get("verified_scope_evidence"), list)
            or len(scope["verified_scope_evidence"]) != 13):
        raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "verified scope evidence is incomplete")
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    seen_legs: set[str] = set()
    for item in scope["verified_scope_evidence"]:
        if (not isinstance(item, Mapping) or not isinstance(item.get("leg"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.+-]+", item["leg"])
                or item["leg"] in {".", ".."}
                or item["leg"] in seen_legs
                or item.get("artifact_name") != f"repro-digest-{item['leg']}"
                or not isinstance(item.get("archives"), list)):
            raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "scope evidence row is malformed")
        leg = item["leg"]
        seen_legs.add(leg)
        if (leg == "sdist" and item["archives"]
                or leg != "sdist" and not item["archives"]):
            raise gate.GateError(gate.SCOPE_UNVERIFIABLE, f"{leg}: runtime archive set is incomplete")
        for archive in item["archives"]:
            if (not isinstance(archive, Mapping)
                    or set(archive) != {"file", "size", "sha256", "name", "version"}
                    or not isinstance(archive["file"], str)
                    or not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", archive["file"])
                    or not isinstance(archive["name"], str)
                    or not isinstance(archive["version"], str)
                    or not isinstance(archive["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", archive["sha256"])
                    or type(archive["size"]) is not int or archive["size"] <= 0):
                raise gate.GateError(gate.SCOPE_UNVERIFIABLE, f"{leg}: archive identity is malformed")
            path = root / item["artifact_name"] / archive["file"]
            raw = gate.read_archive_snapshot(path)
            sha = hashlib.sha256(raw).hexdigest()
            if sha != archive["sha256"] or len(raw) != archive["size"]:
                raise gate.GateError(gate.SOURCE_HASH_MISMATCH, f"{leg}: archive bytes changed after transport")
            key = f"pypi/{archive['name']}@{archive['version']}"
            identity = (key, sha)
            if identity in rows:
                rows[identity]["legs"].append(leg)
                continue
            declared = gate.distribution_declared_metadata(path, archive["name"], archive["version"])
            bound = gate.archive_license_evidence(raw, "pypi")
            if bound["source_sha256"] != sha:
                raise gate.GateError(gate.SOURCE_HASH_MISMATCH, f"{key}: licence evidence changed")
            member_names = [member["name"] for member in bound["archive_members"]
                            if member["type"] == "file"]
            evidence = {**declared, **bound,
                        "install_hook_sources": {name: "" for name in member_names
                                                 if name.endswith(("/setup.py", "/build.rs"))},
                        "parsed_inputs": [name for name in member_names if name.endswith(".py")],
                        "native_libraries": [{"path": name} for name in member_names
                                             if name.endswith((".so", ".pyd", ".dylib"))],
                        "known_vulnerabilities": []}
            failures, decision, source = gate.evaluate_dependency_license(
                evidence, key, None,
            )
            if failures:
                raise gate.GateError(failures[0].code, f"{key}: {failures[0].detail}")
            fixture_key = f"{key}/sha256/{sha}"
            fixture = gate.build_fixture(gate.Dependency("pypi", archive["name"], archive["version"]), evidence)
            fixture["id"] = fixture_key
            rows[identity] = {"key": fixture_key, "package_key": key, "name": archive["name"],
                              "version": archive["version"], "source_sha256": sha,
                              "license": decision.selected, "license_source": source,
                              "license_member_sha256": bound["license_member_sha256"],
                              "fixture": fixture, "fixture_sha256": gate.fixture_digest(fixture),
                              "legs": [leg]}
    if len(seen_legs) != 13 or "sdist" not in seen_legs or not rows:
        raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "runtime archive coverage is incomplete")
    return sorted(rows.values(), key=lambda row: (row["key"], row["source_sha256"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verified-scope", required=True)
    parser.add_argument("--scope-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        raise gate.GateError(gate.CAPTURE_INCOMPLETE, "archive license output already exists")
    result = prescreen(_json_bytes(Path(args.verified_scope).read_bytes()), Path(args.scope_root))
    output.write_text(json.dumps({"schema": "cwl.release-runtime-archive-licenses/1",
                                  "archives": result}, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
