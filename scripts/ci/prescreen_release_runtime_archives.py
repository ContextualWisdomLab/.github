#!/usr/bin/env python3
"""Prescreen exact transported runtime wheels before Strix credentials exist."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

try:
    from scripts.ci import release_dependency_gate as gate
    from scripts.ci.verify_release_distribution_set import _json_bytes
except ImportError:  # pragma: no cover - trusted direct `python3 -I` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import release_dependency_gate as gate
    from verify_release_distribution_set import _json_bytes


def _build_packages(item: Mapping[str, Any], folder: Path) -> list[dict[str, Any]]:
    """Review the exact installed files recorded by one build interpreter."""
    leg = item["leg"]
    receipt = _json_bytes((folder / f"{leg}.build-first.json").read_bytes())
    if not isinstance(receipt, Mapping) or receipt.get("leg") != leg:
        raise gate.GateError(gate.SCOPE_UNVERIFIABLE, f"{leg}: build receipt is malformed")
    snapshot = folder / f"{leg}.build-python.zip"
    raw_sha = hashlib.sha256(gate.read_archive_snapshot(snapshot)).hexdigest()
    if receipt.get("python_snapshot_sha256") != raw_sha or item.get("members", {}).get(snapshot.name) != raw_sha:
        raise gate.GateError(gate.SOURCE_HASH_MISMATCH, f"{leg}: build snapshot changed after transport")
    packages = receipt.get("python_packages")
    if not isinstance(packages, list) or not packages:
        raise gate.GateError(gate.SCOPE_UNVERIFIABLE, f"{leg}: build packages are missing")
    result = []
    with zipfile.ZipFile(snapshot) as archive:
        members = {entry.filename: entry for entry in archive.infolist()}
        for package in packages:
            name, version = package["name"], package["version"]
            files = package["files"]
            metadata = [file["path"] for file in files if file["path"].endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} metadata is ambiguous")
            metadata_root = PurePosixPath(metadata[0]).parent
            def read_file(path: str) -> bytes:
                entry = members.get(f"{name}/{path}")
                if entry is None or entry.file_size > 4 * 1024 * 1024:
                    raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} text file is missing or oversized")
                with archive.open(entry) as stream:
                    return stream.read(4 * 1024 * 1024 + 1)
            try:
                message = email.parser.BytesParser().parsebytes(read_file(metadata[0]))
            except (UnicodeError, ValueError) as error:
                raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} metadata is unreadable") from error
            if (gate.normalize_project_name(str(message.get("Name", ""))) != name
                    or message.get("Version", "") != version):
                raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} metadata differs from installed identity")
            candidates = {file["path"] for file in files if PurePosixPath(file["path"]).name.upper().startswith(
                ("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE"))}
            for declared in message.get_all("License-File", []):
                path = PurePosixPath(declared)
                if path.is_absolute() or ".." in path.parts or "\\" in declared:
                    raise gate.GateError(gate.ARCHIVE_PATH_ESCAPE, f"{leg}: {name} license path is unsafe")
                matches = {str(metadata_root / path), str(metadata_root / "licenses" / path)}
                present = matches & {file["path"] for file in files}
                if not present:
                    raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} declared license is missing")
                candidates.update(present)
            texts = {}
            hashes = {}
            total = 0
            for path in sorted(candidates):
                data = read_file(path)
                total += len(data)
                if total > 16 * 1024 * 1024:
                    raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} license text set is oversized")
                try:
                    texts[path] = data.decode("utf-8")
                except UnicodeError as error:
                    raise gate.GateError(gate.CAPTURE_INCOMPLETE, f"{leg}: {name} license text is undecodable") from error
                hashes[path] = hashlib.sha256(data).hexdigest()
            source_sha = hashlib.sha256(gate.canonical_json({"name": name, "version": version,
                                                              "files": files})).hexdigest()
            key = f"pypi/{name}@{version}"
            evidence = {"source_sha256": source_sha,
                        "license_expression": message.get("License-Expression", ""),
                        "license": message.get("License", ""),
                        "classifiers": message.get_all("Classifier", []),
                        "license_texts": texts, "license_member_sha256": hashes,
                        "archive_members": [{"type": "file", "name": file["path"], "linkname": ""}
                                            for file in files],
                        "install_hook_sources": {},
                        "parsed_inputs": [file["path"] for file in files if file["path"].endswith(".py")],
                        "native_libraries": [{"path": file["path"]} for file in files
                                             if file["path"].endswith((".so", ".pyd", ".dylib"))],
                        "known_vulnerabilities": []}
            failures, decision, source = gate.evaluate_dependency_license(evidence, key, None)
            if failures:
                raise gate.GateError(failures[0].code, f"{leg}: {key}: {failures[0].detail}")
            fixture_key = f"{key}/sha256/{source_sha}"
            fixture = gate.build_fixture(gate.Dependency("pypi", name, version), evidence)
            fixture["id"] = fixture_key
            result.append({"key": fixture_key, "package_key": key, "name": name,
                           "version": version, "source_sha256": source_sha,
                           "license": decision.selected, "license_source": source,
                           "license_member_sha256": hashes, "fixture": fixture,
                           "fixture_sha256": gate.fixture_digest(fixture),
                           "legs": [leg], "snapshots": {leg: raw_sha}})
    return result


def prescreen(scope: Any, root: Path) -> dict[str, list[dict[str, Any]]]:
    """Rebind every wheel byte and apply the existing licence decision path."""
    if (not isinstance(scope, Mapping)
            or not isinstance(scope.get("verified_scope_evidence"), list)
            or len(scope["verified_scope_evidence"]) != 13):
        raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "verified scope evidence is incomplete")
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    build_rows: dict[str, dict[str, Any]] = {}
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
        for package in _build_packages(item, root / item["artifact_name"]):
            if package["key"] in build_rows:
                build_rows[package["key"]]["legs"].append(leg)
                build_rows[package["key"]]["snapshots"][leg] = package["snapshots"][leg]
            else:
                build_rows[package["key"]] = package
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
    return {"archives": sorted(rows.values(), key=lambda row: (row["key"], row["source_sha256"])),
            "build_packages": sorted(build_rows.values(), key=lambda row: row["key"])}


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
    output.write_text(json.dumps({"schema": "cwl.release-runtime-archive-licenses/2",
                                  **result}, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
