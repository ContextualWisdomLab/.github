#!/usr/bin/env python3
"""Fail-closed pre-publish dependency gate for org releases (issue #2342).

``scripts/ci/sbom_inventory_aggregator.py`` is a *scheduled, informational* org
SBOM roll-up: it flags GPL/AGPL/NOASSERTION components for governance, but it
is not per-dependency, not fail-closed, and not bound to a release head. This
module is the missing gate. It runs in
``.github/workflows/release-dependency-license-strix-gate.yml`` **before** a
release workflow publishes anything, and it either exits ``0`` or refuses the
release. There is no neutral outcome, no allow-failure, and no bypass.

Design: the gate is a pure function over *captured* inputs. Workflow steps run
``pip inspect``, ``cargo metadata --locked``, archive listing, ``readelf -d``,
and Strix; each writes a file into a capture directory. This module only reads
files. That split keeps every deterministic decision unit-testable without a
runner and makes the Actions-only parts explicit instead of simulated.

Capture layout (produced by the workflow, consumed here)::

    <capture>/
      release.json                      source repository/SHA + artifact names
      python/lock.txt                   the hash-pinned lock that was installed
      python/installed.json             `pip inspect` of the build environment
      cargo/Cargo.lock                  the committed Cargo lock
      cargo/metadata.json               `cargo metadata --format-version 1 --locked`
      evidence/<slug>.json              per-dependency captured evidence
      strix/bindings/<slug>.json        per-dependency Strix structured binding
      license-selections.json           optional dual-license selections

Every resolved dependency of both ecosystems must appear in the lock *and* in
the environment/build graph; any asymmetry fails ``LOCK_ENV_MISMATCH`` or
``CARGO_LOCK_GRAPH_MISMATCH``. No dependency is exempt: bootstrap tools such as
``pip`` are pinned in this organization's own ``*-hashes.txt`` files, so a lock
that omits an installed distribution is a defect, not a special case.

Strix evidence is accepted **only** as a machine-readable binding. A textual
"0 findings" or "No exploitable vulnerabilities detected" is rejected
(``STRIX_TEXTUAL_PASS_REJECTED``), and a missing or malformed binding is a
failure rather than a neutral result. The binding's fail-closed shape and error
type follow ``scripts/ci/strix_evidence_binding.py``, which is imported from
this script's **own** directory so the gate behaves identically wherever the
trusted verifier is materialized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from scripts.ci.spdx_license_policy import (
        LICENSE_MISSING,
        LicenseDecision,
        evaluate_license_expression,
        scan_license_text,
        spdx_from_classifiers,
    )
except ImportError:  # pragma: no cover - direct `python3 -I <script>` execution in CI
    # Python 3.11+ makes `-I` imply `-P`, so sys.path carries neither the
    # invoking directory nor the script's own directory. Resolve the sibling
    # policy module the same way the Strix binder is resolved: next to this
    # script, by its real path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from spdx_license_policy import (
        LICENSE_MISSING,
        LicenseDecision,
        evaluate_license_expression,
        scan_license_text,
        spdx_from_classifiers,
    )

# ---------------------------------------------------------------------------
# Trusted-path binder resolution (same semantics as strix_quick_gate.sh, but
# resolved next to *this* script rather than against a repository root).
# ---------------------------------------------------------------------------

BINDER_FILENAME = "strix_evidence_binding.py"


def resolve_evidence_binder(script_dir: Path | None = None) -> Path:
    """Return the Strix binder that sits next to this script, failing closed."""

    directory = (script_dir or Path(__file__).resolve().parent).resolve()
    binder = directory / BINDER_FILENAME
    if binder.is_symlink() or not binder.is_file():
        raise GateError(
            "STRIX_BINDER_UNAVAILABLE",
            f"trusted Strix evidence binder is missing at {binder}",
        )
    return binder


# ---------------------------------------------------------------------------
# Stable failure codes. Tests assert on these; never on prose.
# ---------------------------------------------------------------------------

CAPTURE_INCOMPLETE = "CAPTURE_INCOMPLETE"
LOCK_UNPINNED = "LOCK_UNPINNED"
LOCK_ENV_MISMATCH = "LOCK_ENV_MISMATCH"
CARGO_LOCK_GRAPH_MISMATCH = "CARGO_LOCK_GRAPH_MISMATCH"
CARGO_CHECKSUM_MISSING = "CARGO_CHECKSUM_MISSING"
EVIDENCE_MISSING = "EVIDENCE_MISSING"
EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
SOURCE_HASH_MISMATCH = "SOURCE_HASH_MISMATCH"
LICENSE_TEXT_DISAGREEMENT = "LICENSE_TEXT_DISAGREEMENT"
LICENSE_DENIED_IN_BUNDLED_TEXT = "LICENSE_DENIED_IN_BUNDLED_TEXT"
NATIVE_LINK_DENIED = "NATIVE_LINK_DENIED"
NATIVE_LINK_UNKNOWN = "NATIVE_LINK_UNKNOWN"
ARCHIVE_PATH_ESCAPE = "ARCHIVE_PATH_ESCAPE"
INSTALL_HOOK = "INSTALL_HOOK"
STRIX_BINDING_MISSING = "STRIX_BINDING_MISSING"
STRIX_BINDING_MALFORMED = "STRIX_BINDING_MALFORMED"
STRIX_BINDING_UNBOUND = "STRIX_BINDING_UNBOUND"
STRIX_TEXTUAL_PASS_REJECTED = "STRIX_TEXTUAL_PASS_REJECTED"
STRIX_FINDINGS_OPEN = "STRIX_FINDINGS_OPEN"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_NORMALIZE_RE = re.compile(r"[-_.]+")
_MAX_JSON_BYTES = 16 * 1024 * 1024

CYCLONEDX_SCHEMA = "https://cyclonedx.org/schema/bom-1.7.schema.json"
CYCLONEDX_PREDICATE_TYPE = "https://cyclonedx.org/bom"
SOURCE_IDENTITY_FILENAME = "source-identity.json"
CHECKSUM_FILENAME = "checksums.sha256"
FILENAME_PROPERTY = "cwl:artifact:filename"

FIXTURE_SCHEMA = "cwl.release-dependency-fixture/1"
BINDING_SCHEMA = "cwl.release-dependency-strix-binding/1"
BINDING_VERDICTS = frozenset({"no_exploitable_findings", "findings_present"})

#: Every synthetic fixture simulates exactly these adversarial surfaces.
REQUIRED_SCENARIOS: tuple[str, ...] = (
    "archive_traversal",
    "credential_network",
    "file_parsing",
    "install_hooks",
    "known_vulnerability_surface",
    "native_library_loading",
)

#: Platform runtime sonames every compiled wheel and every Rust binary links.
#: Denying LGPL/GPL outright without this allowlist would fail the GREEN case on
#: any real artifact, including fast-mlsirm's own maturin wheel. Each entry is
#: copied into the SBOM component properties so the exemption is auditable.
SYSTEM_RUNTIME_SONAMES: dict[str, tuple[str, str]] = {
    "ld-linux-x86-64.so.2": ("LGPL-2.1-or-later", "glibc dynamic loader, OS-provided"),
    "libc.so.6": ("LGPL-2.1-or-later", "glibc C runtime, dynamically linked, OS-provided"),
    "libdl.so.2": ("LGPL-2.1-or-later", "glibc dynamic-loading shim, OS-provided"),
    "libgcc_s.so.1": (
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "GCC unwinder; the runtime-library exception permits proprietary linking",
    ),
    "libgomp.so.1": (
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "GCC OpenMP runtime; runtime-library exception applies",
    ),
    "libm.so.6": ("LGPL-2.1-or-later", "glibc math runtime, dynamically linked"),
    "libpthread.so.0": ("LGPL-2.1-or-later", "glibc threading runtime, dynamically linked"),
    "libresolv.so.2": ("LGPL-2.1-or-later", "glibc resolver runtime, dynamically linked"),
    "librt.so.1": ("LGPL-2.1-or-later", "glibc realtime runtime, dynamically linked"),
    "libstdc++.so.6": (
        "GPL-3.0-or-later WITH GCC-exception-3.1",
        "GCC C++ runtime; runtime-library exception applies",
    ),
    "libutil.so.1": ("LGPL-2.1-or-later", "glibc utility runtime, dynamically linked"),
}

_LIBPYTHON_RE = re.compile(r"^libpython3\.\d+m?\.so(?:\.\d+\.\d+)?$")

#: Source patterns that make an install/build hook untrusted.
_HOOK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("subprocess.", "spawns a subprocess"),
    ("os.system(", "spawns a shell"),
    ("os.popen(", "spawns a shell"),
    ("urllib.request", "performs a network request"),
    ("http.client", "performs a network request"),
    ("requests.", "performs a network request"),
    ("socket.socket", "opens a socket"),
    ("std::process::Command", "spawns a subprocess"),
    ("reqwest::", "performs a network request"),
)
_CMDCLASS_COMMANDS: tuple[str, ...] = ("install", "develop", "egg_info")


class GateError(ValueError):
    """A fail-closed gate error carrying a stable machine-readable code."""

    def __init__(self, code: str, detail: str) -> None:
        """Store the stable failure code alongside its human-readable detail."""
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Failure:
    """One refusal reason attributed to a subject (a dependency key or input)."""

    code: str
    subject: str
    detail: str

    def to_json(self) -> dict[str, str]:
        """Serialize this failure for the gate report artifact."""
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class Dependency:
    """One resolved dependency of the release, in either ecosystem."""

    ecosystem: str
    name: str
    version: str
    expected_hashes: frozenset[str] = frozenset()

    @property
    def key(self) -> str:
        """Return the canonical ``ecosystem/name@version`` identity."""
        return f"{self.ecosystem}/{self.name}@{self.version}"

    @property
    def slug(self) -> str:
        """Return the filesystem-safe capture filename stem for this dependency."""
        return self.key.replace("/", "__").replace("@", "__")


@dataclass
class GateReport:
    """The gate's complete verdict plus the provenance it hands downstream."""

    source_repository: str
    source_sha: str
    binder_sha256: str = ""
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Return whether the release may proceed; any failure refuses it."""
        return not self.failures

    def to_json(self) -> dict[str, Any]:
        """Serialize the gate verdict deterministically for CI artifacts."""
        return {
            "schema": "cwl.release-dependency-gate/1",
            "result": "PASS" if self.passed else "FAIL",
            "source_repository": self.source_repository,
            "source_sha": self.source_sha,
            "strix_evidence_binder_sha256": self.binder_sha256,
            "dependency_count": len(self.dependencies),
            "dependencies": sorted(self.dependencies, key=lambda row: row["key"]),
            "failures": sorted(
                (failure.to_json() for failure in self.failures),
                key=lambda row: (row["code"], row["subject"]),
            ),
        }


# ---------------------------------------------------------------------------
# Capture loading helpers
# ---------------------------------------------------------------------------


def _require_regular_file(path: Path, code: str) -> Path:
    """Reject symlinks, directories, and missing capture members."""

    if path.is_symlink() or not path.is_file():
        raise GateError(code, f"required capture member is missing: {path}")
    return path


def load_json(path: Path, code: str = CAPTURE_INCOMPLETE) -> Any:
    """Load one bounded JSON capture file, failing closed on any defect."""

    _require_regular_file(path, code)
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise GateError(code, f"capture member exceeds the size limit: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError(code, f"capture member is not valid JSON: {path} ({error})") from error


def normalize_project_name(name: str) -> str:
    """Return the PEP 503 normalized form of a Python project name."""

    return _NORMALIZE_RE.sub("-", name).lower()


def _require_list(evidence: Mapping[str, Any], key: str, subject: str) -> list[Any]:
    """Return one captured evidence array, failing closed on any other shape."""

    value = evidence.get(key, [])
    if not isinstance(value, list):
        raise GateError(EVIDENCE_INCOMPLETE, f"{subject}: {key} must be an array")
    return value


def _require_mapping(evidence: Mapping[str, Any], key: str, subject: str) -> Mapping[str, Any]:
    """Return one captured evidence object, failing closed on any other shape."""

    value = evidence.get(key, {})
    if not isinstance(value, Mapping):
        raise GateError(EVIDENCE_INCOMPLETE, f"{subject}: {key} must be an object")
    return value


# ---------------------------------------------------------------------------
# Python enumeration
# ---------------------------------------------------------------------------


def parse_python_lock(text: str) -> dict[tuple[str, str], frozenset[str]]:
    """Parse a hash-pinned requirements lock into ``(name, version) -> hashes``."""

    joined = re.sub(r"\\\s*\n", " ", text)
    entries: dict[tuple[str, str], frozenset[str]] = {}
    for raw in joined.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)\s*==\s*([^\s;]+)", line)
        if match is None:
            raise GateError(LOCK_UNPINNED, f"lock line is not an exact pin: {line!r}")
        name = normalize_project_name(match.group(1))
        version = match.group(2)
        hashes = frozenset(re.findall(r"--hash=sha256:([0-9a-f]{64})", line))
        if not hashes:
            raise GateError(
                LOCK_UNPINNED, f"lock entry {name}=={version} carries no sha256 hash"
            )
        entries[(name, version)] = hashes
    if not entries:
        raise GateError(LOCK_UNPINNED, "python lock declares no pinned requirement")
    return entries


def parse_installed_environment(payload: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Parse ``pip inspect`` output into ``(name, version) -> metadata``."""

    if not isinstance(payload, Mapping) or not isinstance(payload.get("installed"), list):
        raise GateError(
            CAPTURE_INCOMPLETE, "environment capture must be a pip inspect object"
        )
    installed: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in payload["installed"]:
        metadata = item.get("metadata") if isinstance(item, Mapping) else None
        if not isinstance(metadata, Mapping):
            raise GateError(
                CAPTURE_INCOMPLETE, "pip inspect entry carries no metadata object"
            )
        name = metadata.get("name")
        version = metadata.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise GateError(
                CAPTURE_INCOMPLETE, "pip inspect entry carries no name/version pair"
            )
        installed[(normalize_project_name(name), version)] = metadata
    return installed


def reconcile_python(
    lock: Mapping[tuple[str, str], frozenset[str]],
    installed: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[Failure]:
    """Fail when the hash-pinned lock and the build environment disagree."""

    failures: list[Failure] = []
    for entry in sorted(set(lock) - set(installed)):
        failures.append(
            Failure(
                LOCK_ENV_MISMATCH,
                f"pypi/{entry[0]}@{entry[1]}",
                "locked requirement is absent from the build environment",
            )
        )
    for entry in sorted(set(installed) - set(lock)):
        failures.append(
            Failure(
                LOCK_ENV_MISMATCH,
                f"pypi/{entry[0]}@{entry[1]}",
                "installed distribution is absent from the hash-pinned lock",
            )
        )
    return failures


# ---------------------------------------------------------------------------
# Cargo enumeration
# ---------------------------------------------------------------------------


def parse_cargo_lock(text: str) -> dict[tuple[str, str], str | None]:
    """Parse ``Cargo.lock`` into ``(name, version) -> checksum or None``."""

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise GateError(CAPTURE_INCOMPLETE, f"Cargo.lock is not valid TOML: {error}") from error
    packages = document.get("package")
    if not isinstance(packages, list) or not packages:
        raise GateError(CAPTURE_INCOMPLETE, "Cargo.lock declares no packages")
    entries: dict[tuple[str, str], str | None] = {}
    for package in packages:
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise GateError(CAPTURE_INCOMPLETE, "Cargo.lock package lacks name/version")
        checksum = package.get("checksum")
        entries[(name, version)] = checksum if isinstance(checksum, str) else None
    return entries


def _package_identity(package: Mapping[str, Any]) -> tuple[str, str]:
    """Return the ``(name, version)`` identity of one ``cargo metadata`` package."""

    name = package.get("name")
    version = package.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise GateError(CAPTURE_INCOMPLETE, "cargo metadata package lacks name/version")
    return name, version


def resolve_cargo_graph(metadata: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Resolve the full build graph, including build- and target-specific deps."""

    if not isinstance(metadata, Mapping):
        raise GateError(CAPTURE_INCOMPLETE, "cargo metadata capture must be an object")
    packages = metadata.get("packages")
    resolve = metadata.get("resolve")
    if not isinstance(packages, list) or not isinstance(resolve, Mapping):
        raise GateError(CAPTURE_INCOMPLETE, "cargo metadata lacks packages/resolve")
    by_id: dict[str, Mapping[str, Any]] = {}
    for package in packages:
        if not isinstance(package, Mapping) or not isinstance(package.get("id"), str):
            raise GateError(CAPTURE_INCOMPLETE, "cargo metadata package lacks an id")
        by_id[package["id"]] = package
    nodes = resolve.get("nodes")
    root = resolve.get("root")
    if not isinstance(nodes, list) or not isinstance(root, str):
        raise GateError(CAPTURE_INCOMPLETE, "cargo metadata resolve lacks nodes/root")
    edges: dict[str, list[str]] = {}
    for node in nodes:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            raise GateError(CAPTURE_INCOMPLETE, "cargo metadata resolve node lacks an id")
        targets: list[str] = []
        for dependency in node.get("deps", []):
            package_id = dependency.get("pkg") if isinstance(dependency, Mapping) else None
            if not isinstance(package_id, str):
                raise GateError(CAPTURE_INCOMPLETE, "cargo resolve dep lacks a pkg id")
            # Every dep_kind is in scope: normal, build, dev-for-build, and
            # every cfg()-gated target. A build-dependency ships nothing but it
            # executes on the release runner, so it is gated like any other.
            targets.append(package_id)
        edges[node["id"]] = targets
    if root not in edges:
        raise GateError(CAPTURE_INCOMPLETE, "cargo metadata resolve root is not a node")

    reachable: dict[tuple[str, str], Mapping[str, Any]] = {}
    seen: set[str] = set()
    queue = [root]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        package = by_id.get(current)
        if package is None:
            raise GateError(
                CAPTURE_INCOMPLETE, f"cargo resolve names an unknown package id: {current}"
            )
        if current != root:
            reachable[_package_identity(package)] = package
        queue.extend(edges.get(current, []))
    return reachable


def reconcile_cargo(
    lock: Mapping[tuple[str, str], str | None],
    graph: Mapping[tuple[str, str], Mapping[str, Any]],
    root_identity: tuple[str, str],
) -> list[Failure]:
    """Fail when ``Cargo.lock`` and the resolved build graph disagree."""

    failures: list[Failure] = []
    locked = set(lock) - {root_identity}
    for entry in sorted(locked - set(graph)):
        failures.append(
            Failure(
                CARGO_LOCK_GRAPH_MISMATCH,
                f"cargo/{entry[0]}@{entry[1]}",
                "Cargo.lock entry is absent from the resolved build graph",
            )
        )
    for entry in sorted(set(graph) - locked):
        failures.append(
            Failure(
                CARGO_LOCK_GRAPH_MISMATCH,
                f"cargo/{entry[0]}@{entry[1]}",
                "resolved build-graph package is absent from Cargo.lock",
            )
        )
    for entry in sorted(set(graph) & locked):
        if lock[entry] is None:
            failures.append(
                Failure(
                    CARGO_CHECKSUM_MISSING,
                    f"cargo/{entry[0]}@{entry[1]}",
                    "registry dependency has no Cargo.lock checksum",
                )
            )
    return failures


# ---------------------------------------------------------------------------
# Deterministic per-dependency detectors
# ---------------------------------------------------------------------------


def detect_archive_escape(members: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return archive members that escape the extraction root."""

    findings: list[str] = []
    for member in members:
        name = member.get("name")
        if not isinstance(name, str) or not name:
            findings.append("archive member has no name")
            continue
        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            findings.append(f"absolute archive member: {name}")
            continue
        if ".." in Path(name).parts:
            findings.append(f"traversal archive member: {name}")
            continue
        link = member.get("linkname")
        if member.get("type") in {"symlink", "hardlink"} and isinstance(link, str):
            if link.startswith("/") or ".." in Path(link).parts:
                findings.append(f"escaping link {name} -> {link}")
    return findings


def detect_install_hooks(sources: Mapping[str, str]) -> list[str]:
    """Return untrusted install/build hook behaviour found in captured sources."""

    findings: list[str] = []
    for path in sorted(sources):
        text = sources[path]
        if "cmdclass" in text:
            for command in _CMDCLASS_COMMANDS:
                if f'"{command}"' in text or f"'{command}'" in text:
                    findings.append(f"{path} overrides the {command} command via cmdclass")
        for pattern, reason in _HOOK_PATTERNS:
            if pattern in text:
                findings.append(f"{path} {reason} ({pattern})")
    return findings


def classify_soname(soname: str) -> tuple[str, str] | None:
    """Return the allowlisted SPDX id and rationale for a platform runtime soname."""

    allowlisted = SYSTEM_RUNTIME_SONAMES.get(soname)
    if allowlisted is not None:
        return allowlisted
    if _LIBPYTHON_RE.match(soname):
        return ("PSF-2.0", "CPython runtime supplied by the interpreter")
    return None


def evaluate_native_links(
    evidence: Mapping[str, Any], subject: str
) -> tuple[list[Failure], list[dict[str, str]]]:
    """Evaluate dynamic and static linking targets of shipped native libraries."""

    failures: list[Failure] = []
    properties: list[dict[str, str]] = []
    declared = _require_mapping(evidence, "bundled_library_licenses", subject)
    for library in _require_list(evidence, "native_libraries", subject):
        if not isinstance(library, Mapping):
            raise GateError(
                EVIDENCE_INCOMPLETE, f"{subject}: native_libraries entry must be an object"
            )
        origin = str(library.get("path", "<unknown>"))
        for soname in _require_list(library, "needed", subject):
            allowlisted = classify_soname(str(soname))
            if allowlisted is not None:
                properties.append(
                    {
                        "name": "cwl:native:system-runtime",
                        "value": f"{soname}={allowlisted[0]}; {allowlisted[1]}",
                    }
                )
                continue
            decision = evaluate_license_expression(declared.get(str(soname)))
            if decision.allowed:
                properties.append(
                    {
                        "name": "cwl:native:dynamic",
                        "value": f"{soname}={decision.selected}",
                    }
                )
                continue
            failures.append(
                Failure(
                    NATIVE_LINK_UNKNOWN if decision.code == LICENSE_MISSING else NATIVE_LINK_DENIED,
                    subject,
                    f"{origin} dynamically links {soname}: {decision.detail}",
                )
            )
        for archive in _require_list(library, "static_archives", subject):
            if not isinstance(archive, Mapping):
                raise GateError(
                    EVIDENCE_INCOMPLETE, f"{subject}: static_archives entry must be an object"
                )
            archive_name = str(archive.get("name", "<unknown>"))
            decision = evaluate_license_expression(archive.get("license"))
            if decision.allowed:
                properties.append(
                    {
                        "name": "cwl:native:static",
                        "value": f"{archive_name}={decision.selected}",
                    }
                )
                continue
            failures.append(
                Failure(
                    NATIVE_LINK_UNKNOWN if decision.code == LICENSE_MISSING else NATIVE_LINK_DENIED,
                    subject,
                    f"{origin} statically links {archive_name}: {decision.detail}",
                )
            )
    return failures, properties


def declared_license_expression(evidence: Mapping[str, Any]) -> tuple[str | None, str]:
    """Return the declared SPDX expression and the source it was taken from."""

    expression = evidence.get("license_expression")
    if isinstance(expression, str) and expression.strip():
        return expression.strip(), "License-Expression"
    legacy = evidence.get("license")
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip(), "License"
    classifiers = evidence.get("classifiers", [])
    if isinstance(classifiers, list):
        derived = spdx_from_classifiers([str(item) for item in classifiers])
        if derived is not None:
            return derived, "classifier"
    return None, "none"


def evaluate_dependency_license(
    evidence: Mapping[str, Any],
    subject: str,
    selection: Mapping[str, str] | None,
) -> tuple[list[Failure], LicenseDecision, str]:
    """Decide one dependency's license from metadata and bundled license text."""

    expression, source = declared_license_expression(evidence)
    decision = evaluate_license_expression(
        expression,
        selection=(selection or {}).get("chosen"),
        rationale=(selection or {}).get("rationale"),
    )
    failures: list[Failure] = []
    if not decision.allowed:
        failures.append(Failure(decision.code, subject, decision.detail))
    texts = _require_mapping(evidence, "license_texts", subject)
    for filename in sorted(texts):
        code = scan_license_text(str(texts[filename]))
        if code is None:
            continue
        if decision.allowed:
            failures.append(
                Failure(
                    LICENSE_TEXT_DISAGREEMENT,
                    subject,
                    f"declared {expression} but bundled {filename} is {code}",
                )
            )
        else:
            failures.append(
                Failure(
                    LICENSE_DENIED_IN_BUNDLED_TEXT,
                    subject,
                    f"bundled {filename} contains {code} license text",
                )
            )
    return failures, decision, source


# ---------------------------------------------------------------------------
# Synthetic Strix fixtures and structured binding validation
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> bytes:
    """Serialize a value to canonical, deterministic JSON bytes."""

    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_fixture(dependency: Dependency, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build the isolated synthetic Strix fixture for exactly one dependency."""

    members = [
        str(member.get("name", ""))
        for member in _require_list(evidence, "archive_members", dependency.key)
        if isinstance(member, Mapping)
    ]
    sources = _require_mapping(evidence, "install_hook_sources", dependency.key)
    libraries = [
        str(library.get("path", ""))
        for library in _require_list(evidence, "native_libraries", dependency.key)
        if isinstance(library, Mapping)
    ]
    advisories = [
        str(item.get("id", ""))
        for item in _require_list(evidence, "known_vulnerabilities", dependency.key)
        if isinstance(item, Mapping)
    ]
    return {
        "schema": FIXTURE_SCHEMA,
        "dependency": {
            "ecosystem": dependency.ecosystem,
            "name": dependency.name,
            "version": dependency.version,
            "source_sha256": str(evidence.get("source_sha256", "")),
        },
        "scenarios": {
            "archive_traversal": {"members": sorted(members)},
            "credential_network": {
                "probes": [
                    "env:CARGO_REGISTRY_TOKEN",
                    "env:PYPI_API_TOKEN",
                    "net:https://credential-probe.invalid/collect",
                ]
            },
            "file_parsing": {
                "inputs": sorted(
                    str(item) for item in _require_list(evidence, "parsed_inputs", dependency.key)
                )
            },
            "install_hooks": {"sources": sorted(sources)},
            "known_vulnerability_surface": {"advisories": sorted(advisories)},
            "native_library_loading": {"libraries": sorted(libraries)},
        },
    }


def fixture_digest(fixture: Mapping[str, Any]) -> str:
    """Return the deterministic sha256 of one synthetic fixture document."""

    return hashlib.sha256(canonical_json(fixture)).hexdigest()


def validate_strix_binding(
    path: Path,
    dependency: Dependency,
    evidence: Mapping[str, Any],
    digest: str,
    source_sha: str,
) -> list[Failure]:
    """Require a well-formed machine-readable Strix binding; text never passes."""

    subject = dependency.key
    if path.is_symlink() or not path.is_file():
        return [
            Failure(
                STRIX_BINDING_MISSING,
                subject,
                f"no structured Strix binding at {path.name}; a missing binding is a failure",
            )
        ]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [
            Failure(
                STRIX_TEXTUAL_PASS_REJECTED,
                subject,
                "Strix evidence is free text; a textual '0 findings' is never a pass",
            )
        ]
    if not isinstance(payload, Mapping):
        return [
            Failure(
                STRIX_TEXTUAL_PASS_REJECTED,
                subject,
                "Strix evidence is not a binding object; prose is never a pass",
            )
        ]
    if payload.get("schema") != BINDING_SCHEMA:
        code = (
            STRIX_TEXTUAL_PASS_REJECTED
            if {"summary", "report", "report_text", "conclusion"} & set(payload)
            else STRIX_BINDING_MALFORMED
        )
        return [
            Failure(
                code,
                subject,
                f"Strix evidence does not declare the {BINDING_SCHEMA} contract",
            )
        ]

    failures: list[Failure] = []
    bound = payload.get("dependency")
    expected = {
        "ecosystem": dependency.ecosystem,
        "name": dependency.name,
        "version": dependency.version,
        "source_sha256": str(evidence.get("source_sha256", "")),
    }
    if not isinstance(bound, Mapping) or dict(bound) != expected:
        failures.append(
            Failure(
                STRIX_BINDING_UNBOUND,
                subject,
                "binding does not name exactly this dependency name/version/source hash",
            )
        )
    fixture = payload.get("fixture")
    if not isinstance(fixture, Mapping):
        failures.append(
            Failure(STRIX_BINDING_MALFORMED, subject, "binding carries no fixture object")
        )
    else:
        if fixture.get("id") != dependency.key or fixture.get("sha256") != digest:
            failures.append(
                Failure(
                    STRIX_BINDING_UNBOUND,
                    subject,
                    "binding does not name the isolated fixture generated for this dependency",
                )
            )
        scenarios = fixture.get("scenarios")
        if not isinstance(scenarios, list) or sorted(
            str(item) for item in scenarios
        ) != list(REQUIRED_SCENARIOS):
            failures.append(
                Failure(
                    STRIX_BINDING_MALFORMED,
                    subject,
                    f"binding must cover exactly {list(REQUIRED_SCENARIOS)}",
                )
            )
    if payload.get("source_sha") != source_sha:
        failures.append(
            Failure(
                STRIX_BINDING_UNBOUND,
                subject,
                "binding is not bound to the release head SHA",
            )
        )
    findings = payload.get("findings")
    verdict = payload.get("verdict")
    if not isinstance(findings, list) or verdict not in BINDING_VERDICTS:
        failures.append(
            Failure(
                STRIX_BINDING_MALFORMED,
                subject,
                "binding must carry a findings array and an enumerated verdict",
            )
        )
    elif findings or verdict == "findings_present":
        failures.append(
            Failure(
                STRIX_FINDINGS_OPEN,
                subject,
                f"Strix reported {len(findings)} structured finding(s) against the fixture",
            )
        )
    return failures


# ---------------------------------------------------------------------------
# Raw-capture assembly
# ---------------------------------------------------------------------------
#
# ``scripts/ci/release_dependency_capture_raw.sh`` runs the tools that need a
# runner (``pip inspect``, ``cargo metadata --locked``, archive listing,
# ``readelf -d``) and writes their output verbatim under ``raw/<dir>/``. This
# assembler is the tested transformation from that raw output into the capture
# contract the gate reads, so no untested shell decides what evidence says.


def _read_text_files(directory: Path) -> dict[str, str]:
    """Read every regular file in one raw capture directory, keyed by filename."""

    if directory.is_symlink() or not directory.is_dir():
        return {}
    contents: dict[str, str] = {}
    for child in sorted(directory.iterdir()):
        if child.is_symlink() or not child.is_file():
            raise GateError(
                CAPTURE_INCOMPLETE, f"raw capture member is not a regular file: {child}"
            )
        contents[child.name] = child.read_text(encoding="utf-8", errors="replace")
    return contents


def _optional_text(path: Path) -> str | None:
    """Return one optional raw capture file's text, or ``None`` when absent."""

    if path.is_symlink() or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def parse_member_listing(text: str) -> list[dict[str, str]]:
    """Parse the tab-separated ``<type>\t<name>\t<linkname>`` archive listing."""

    members: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise GateError(
                CAPTURE_INCOMPLETE, f"archive listing line is malformed: {line!r}"
            )
        members.append(
            {
                "type": parts[0].strip(),
                "name": parts[1],
                "linkname": parts[2] if len(parts) > 2 else "",
            }
        )
    return members


def build_evidence(raw_dir: Path) -> tuple[Dependency, dict[str, Any]]:
    """Assemble one dependency's capture evidence from its raw capture directory."""

    metadata = load_json(raw_dir / "metadata.json")
    if not isinstance(metadata, Mapping):
        raise GateError(CAPTURE_INCOMPLETE, f"{raw_dir.name}: metadata.json must be an object")
    ecosystem = str(metadata.get("ecosystem", ""))
    name = str(metadata.get("name", ""))
    version = str(metadata.get("version", ""))
    if ecosystem not in {"pypi", "cargo"} or not name or not version:
        raise GateError(
            CAPTURE_INCOMPLETE,
            f"{raw_dir.name}: metadata must declare ecosystem pypi/cargo, name, and version",
        )
    if ecosystem == "pypi":
        name = normalize_project_name(name)
    raw_hash = _optional_text(raw_dir / "source.sha256")
    source_sha256 = raw_hash.split()[0].strip().lower() if raw_hash and raw_hash.split() else ""
    members_text = _optional_text(raw_dir / "members.txt")
    parsed_text = _optional_text(raw_dir / "parsed_inputs.txt")
    native_path = raw_dir / "native.json"
    bundled_path = raw_dir / "bundled_library_licenses.json"
    evidence: dict[str, Any] = {
        "ecosystem": ecosystem,
        "name": name,
        "version": version,
        "source_sha256": source_sha256,
        "license_expression": metadata.get("license_expression"),
        "license": metadata.get("license"),
        "classifiers": list(metadata.get("classifiers", [])),
        "distribution_inclusion": list(metadata.get("distribution_inclusion", [])),
        "known_vulnerabilities": list(metadata.get("known_vulnerabilities", [])),
        "license_texts": _read_text_files(raw_dir / "licenses"),
        "install_hook_sources": _read_text_files(raw_dir / "hooks"),
        "archive_members": parse_member_listing(members_text or ""),
        "parsed_inputs": [line for line in (parsed_text or "").splitlines() if line.strip()],
        "native_libraries": load_json(native_path) if native_path.is_file() else [],
        "bundled_library_licenses": load_json(bundled_path) if bundled_path.is_file() else {},
    }
    return Dependency(ecosystem, name, version), evidence


def capture(raw_root: Path, capture_root: Path) -> list[str]:
    """Write per-dependency evidence and isolated synthetic fixtures from raw output."""

    raw_root = Path(raw_root)
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise GateError(CAPTURE_INCOMPLETE, f"raw capture root is missing: {raw_root}")
    evidence_dir = capture_root / "evidence"
    fixture_dir = capture_root / "strix" / "fixtures"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for child in sorted(raw_root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            raise GateError(CAPTURE_INCOMPLETE, f"raw capture entry is not a directory: {child}")
        dependency, evidence = build_evidence(child)
        (evidence_dir / f"{dependency.slug}.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        fixture = build_fixture(dependency, evidence)
        (fixture_dir / f"{dependency.slug}.json").write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # The canonical digest is published beside the fixture so the Strix step
        # binds the exact document the gate will recompute, not the pretty-printed
        # bytes it happens to read from disk.
        (fixture_dir / f"{dependency.slug}.sha256").write_text(
            fixture_digest(fixture) + "\n", encoding="utf-8"
        )
        written.append(dependency.key)
    if not written:
        raise GateError(CAPTURE_INCOMPLETE, "raw capture root contains no dependency directory")
    return written


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


def _load_selections(capture: Path) -> dict[str, Mapping[str, str]]:
    """Load optional dual-license selections, keyed by dependency identity."""

    path = capture / "license-selections.json"
    if not path.exists():
        return {}
    payload = load_json(path)
    if not isinstance(payload, list):
        raise GateError(CAPTURE_INCOMPLETE, "license-selections.json must be a JSON array")
    selections: dict[str, Mapping[str, str]] = {}
    for item in payload:
        if not isinstance(item, Mapping):
            raise GateError(CAPTURE_INCOMPLETE, "license selection entry must be an object")
        required = {"ecosystem", "name", "version", "chosen", "rationale"}
        if not required.issubset(item):
            raise GateError(
                CAPTURE_INCOMPLETE,
                f"license selection must declare {sorted(required)}",
            )
        key = f"{item['ecosystem']}/{item['name']}@{item['version']}"
        selections[key] = {"chosen": str(item["chosen"]), "rationale": str(item["rationale"])}
    return selections


def _enumerate_python(capture: Path) -> tuple[list[Dependency], list[Failure]]:
    """Enumerate Python dependencies from the lock and the build environment."""

    lock = parse_python_lock(
        _require_regular_file(capture / "python" / "lock.txt", CAPTURE_INCOMPLETE).read_text(
            encoding="utf-8"
        )
    )
    installed = parse_installed_environment(load_json(capture / "python" / "installed.json"))
    failures = reconcile_python(lock, installed)
    dependencies = [
        Dependency("pypi", name, version, lock[(name, version)])
        for (name, version) in sorted(set(lock) & set(installed))
    ]
    return dependencies, failures


def _enumerate_cargo(capture: Path) -> tuple[list[Dependency], list[Failure]]:
    """Enumerate Cargo dependencies from Cargo.lock and the resolved build graph."""

    lock = parse_cargo_lock(
        _require_regular_file(capture / "cargo" / "Cargo.lock", CAPTURE_INCOMPLETE).read_text(
            encoding="utf-8"
        )
    )
    metadata = load_json(capture / "cargo" / "metadata.json")
    graph = resolve_cargo_graph(metadata)
    root_package = next(
        package
        for package in metadata["packages"]
        if package["id"] == metadata["resolve"]["root"]
    )
    root_identity = _package_identity(root_package)
    failures = reconcile_cargo(lock, graph, root_identity)
    dependencies = [
        Dependency("cargo", name, version, frozenset({lock[(name, version)]}))
        for (name, version) in sorted(set(graph) & (set(lock) - {root_identity}))
        if lock[(name, version)] is not None
    ]
    return dependencies, failures


def _dependency_row(
    dependency: Dependency,
    evidence: Mapping[str, Any],
    decision: LicenseDecision,
    license_source: str,
    inclusion: list[str],
    properties: list[dict[str, str]],
    digest: str,
) -> dict[str, Any]:
    """Build the per-dependency structured evidence row for the SBOM and report."""

    return {
        "key": dependency.key,
        "ecosystem": dependency.ecosystem,
        "name": dependency.name,
        "version": dependency.version,
        "source_sha256": str(evidence.get("source_sha256", "")),
        "license": decision.selected,
        "license_source": license_source,
        "license_selection_rationale": decision.rationale,
        "distribution_inclusion": inclusion,
        "native_properties": properties,
        "fixture_sha256": digest,
    }


def gate(capture_root: Path) -> GateReport:
    """Run the complete fail-closed gate over one captured release."""

    capture = Path(capture_root)
    release = load_json(capture / "release.json")
    if not isinstance(release, Mapping):
        raise GateError(CAPTURE_INCOMPLETE, "release.json must be a JSON object")
    repository = str(release.get("source_repository", ""))
    source_sha = str(release.get("source_sha", ""))
    if not REPOSITORY_RE.fullmatch(repository):
        raise GateError(CAPTURE_INCOMPLETE, "release.source_repository must be owner/name")
    if not GIT_SHA_RE.fullmatch(source_sha):
        raise GateError(CAPTURE_INCOMPLETE, "release.source_sha must be a 40-hex commit SHA")
    ecosystems = release.get("ecosystems")
    if not isinstance(ecosystems, list) or not ecosystems:
        raise GateError(CAPTURE_INCOMPLETE, "release.ecosystems must be a non-empty array")

    report = GateReport(source_repository=repository, source_sha=source_sha)
    dependencies: list[Dependency] = []
    if "python" in ecosystems:
        found, failures = _enumerate_python(capture)
        dependencies.extend(found)
        report.failures.extend(failures)
    if "cargo" in ecosystems:
        found, failures = _enumerate_cargo(capture)
        dependencies.extend(found)
        report.failures.extend(failures)
    if not dependencies:
        raise GateError(CAPTURE_INCOMPLETE, "no resolved dependency was enumerated")

    selections = _load_selections(capture)
    report.binder_sha256 = hashlib.sha256(resolve_evidence_binder().read_bytes()).hexdigest()
    for dependency in dependencies:
        subject = dependency.key
        evidence_path = capture / "evidence" / f"{dependency.slug}.json"
        if evidence_path.is_symlink() or not evidence_path.is_file():
            report.failures.append(
                Failure(EVIDENCE_MISSING, subject, "no captured per-dependency evidence")
            )
            continue
        evidence = load_json(evidence_path, EVIDENCE_MISSING)
        if not isinstance(evidence, Mapping):
            raise GateError(EVIDENCE_INCOMPLETE, f"{subject}: evidence must be an object")

        source_hash = str(evidence.get("source_sha256", ""))
        if not SHA256_RE.fullmatch(source_hash):
            report.failures.append(
                Failure(SOURCE_HASH_MISMATCH, subject, "evidence carries no sha256 source hash")
            )
        elif source_hash not in dependency.expected_hashes:
            report.failures.append(
                Failure(
                    SOURCE_HASH_MISMATCH,
                    subject,
                    "captured source hash is not the hash the lock pinned",
                )
            )

        inclusion = evidence.get("distribution_inclusion")
        if (
            not isinstance(inclusion, list)
            or not inclusion
            or not set(inclusion).issubset({"wheel", "sdist", "crate"})
        ):
            raise GateError(
                EVIDENCE_INCOMPLETE,
                f"{subject}: distribution_inclusion must name wheel/sdist/crate",
            )

        license_failures, decision, license_source = evaluate_dependency_license(
            evidence, subject, selections.get(subject)
        )
        report.failures.extend(license_failures)

        native_failures, properties = evaluate_native_links(evidence, subject)
        report.failures.extend(native_failures)

        for finding in detect_archive_escape(
            [
                member
                for member in _require_list(evidence, "archive_members", subject)
                if isinstance(member, Mapping)
            ]
        ):
            report.failures.append(Failure(ARCHIVE_PATH_ESCAPE, subject, finding))

        sources = _require_mapping(evidence, "install_hook_sources", subject)
        for finding in detect_install_hooks({key: str(sources[key]) for key in sources}):
            report.failures.append(Failure(INSTALL_HOOK, subject, finding))

        fixture = build_fixture(dependency, evidence)
        digest = fixture_digest(fixture)
        report.failures.extend(
            validate_strix_binding(
                capture / "strix" / "bindings" / f"{dependency.slug}.json",
                dependency,
                evidence,
                digest,
                source_sha,
            )
        )
        report.dependencies.append(
            _dependency_row(
                dependency,
                evidence,
                decision,
                license_source,
                sorted(inclusion),
                properties,
                digest,
            )
        )
    return report


# ---------------------------------------------------------------------------
# Sealed-evidence composition with exact-artifact-sbom-attestation.yml
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return the streaming sha256 of one file on disk."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cyclonedx_serial_number(subject_name: str, subject_sha256: str) -> str:
    """Return the canonical UUIDv5 serial number the attestation verifier expects."""

    identity = f"urn:cwl:artifact:{subject_name}:sha256:{subject_sha256}"
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, identity)}"


def build_cyclonedx(
    subject_name: str, subject_sha256: str, rows: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Build the CycloneDX 1.7 SBOM that covers exactly the gated dependency set."""

    components = []
    for row in sorted(rows, key=lambda item: item["key"]):
        properties = [
            {"name": "cwl:dependency:license-source", "value": str(row["license_source"])},
            {"name": "cwl:dependency:inclusion", "value": ",".join(row["distribution_inclusion"])},
            {"name": "cwl:dependency:fixture-sha256", "value": str(row["fixture_sha256"])},
        ]
        if row["license_selection_rationale"]:
            properties.append(
                {
                    "name": "cwl:dependency:license-selection-rationale",
                    "value": str(row["license_selection_rationale"]),
                }
            )
        properties.extend(row["native_properties"])
        components.append(
            {
                "type": "library",
                "name": row["name"],
                "version": row["version"],
                "licenses": [{"expression": row["license"]}],
                "hashes": [{"alg": "SHA-256", "content": row["source_sha256"]}],
                "properties": properties,
            }
        )
    return {
        "$schema": CYCLONEDX_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": cyclonedx_serial_number(subject_name, subject_sha256),
        "version": 1,
        "metadata": {
            "component": {
                "type": "file",
                "name": subject_name,
                "properties": [{"name": FILENAME_PROPERTY, "value": subject_name}],
                "hashes": [{"alg": "SHA-256", "content": subject_sha256}],
            }
        },
        "components": components,
    }


def seal(
    report_path: Path,
    wheel: Path,
    sdist: Path,
    evidence_root: Path,
    evidence_artifact_name: str,
) -> dict[str, str]:
    """Write the six-member sealed evidence directory and return handoff outputs."""

    report = load_json(report_path)
    if not isinstance(report, Mapping) or report.get("result") != "PASS":
        raise GateError(
            CAPTURE_INCOMPLETE, "refusing to seal evidence for a non-PASS gate report"
        )
    evidence_root.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {
        "source_repository": str(report["source_repository"]),
        "source_sha": str(report["source_sha"]),
        "predicate_type": CYCLONEDX_PREDICATE_TYPE,
        "cyclonedx_schema": CYCLONEDX_SCHEMA,
        "evidence_artifact_name": evidence_artifact_name,
    }
    rows = report["dependencies"]
    digests: dict[str, str] = {}
    for label, path in (("wheel", wheel), ("sdist", sdist)):
        filename = path.name
        target = evidence_root / filename
        target.write_bytes(path.read_bytes())
        artifact_sha = _sha256_file(target)
        sbom_name = f"{filename}.cdx.json"
        sbom = build_cyclonedx(filename, artifact_sha, rows)
        (evidence_root / sbom_name).write_text(
            json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        digests[filename] = artifact_sha
        digests[sbom_name] = _sha256_file(evidence_root / sbom_name)
        outputs[f"{label}_filename"] = filename
        outputs[f"{label}_sha256"] = artifact_sha
        outputs[f"{label}_sbom_filename"] = sbom_name
        outputs[f"{label}_sbom_sha256"] = digests[sbom_name]

    identity = {
        "schema_version": "1.0",
        "source_repository": outputs["source_repository"],
        "source_sha": outputs["source_sha"],
        "evidence_artifact_name": evidence_artifact_name,
        "predicate_type": CYCLONEDX_PREDICATE_TYPE,
        "cyclonedx_schema": CYCLONEDX_SCHEMA,
        "artifacts": {
            "wheel": {
                "filename": outputs["wheel_filename"],
                "sha256": outputs["wheel_sha256"],
                "sbom_filename": outputs["wheel_sbom_filename"],
                "sbom_sha256": outputs["wheel_sbom_sha256"],
            },
            "sdist": {
                "filename": outputs["sdist_filename"],
                "sha256": outputs["sdist_sha256"],
                "sbom_filename": outputs["sdist_sbom_filename"],
                "sbom_sha256": outputs["sdist_sbom_sha256"],
            },
        },
    }
    identity_path = evidence_root / SOURCE_IDENTITY_FILENAME
    identity_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digests[SOURCE_IDENTITY_FILENAME] = _sha256_file(identity_path)
    outputs["source_identity_sha256"] = digests[SOURCE_IDENTITY_FILENAME]

    checksum_path = evidence_root / CHECKSUM_FILENAME
    checksum_path.write_text(
        "".join(f"{digests[name]}  {name}\n" for name in sorted(digests)), encoding="utf-8"
    )
    outputs["checksum_sha256"] = _sha256_file(checksum_path)
    return outputs


def write_github_output(outputs: Mapping[str, str], destination: Path | None) -> None:
    """Append gate outputs to ``$GITHUB_OUTPUT`` so the caller can chain them."""

    if destination is None:
        return
    with destination.open("a", encoding="utf-8") as handle:
        for key in sorted(outputs):
            handle.write(f"{key}={outputs[key]}\n")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: ``gate`` refuses a release; ``seal`` composes the attestation."""

    parser = argparse.ArgumentParser(description="Pre-publish dependency gate")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("capture", help="Assemble evidence and fixtures from raw output")
    collect.add_argument("--raw", required=True)
    collect.add_argument("--capture", required=True)

    run = sub.add_parser("gate", help="Refuse the release unless every check passes")
    run.add_argument("--capture", required=True)
    run.add_argument("--report", required=True)

    compose = sub.add_parser("seal", help="Seal gated bytes for exact-artifact attestation")
    compose.add_argument("--report", required=True)
    compose.add_argument("--wheel", required=True)
    compose.add_argument("--sdist", required=True)
    compose.add_argument("--evidence-root", required=True)
    compose.add_argument("--evidence-artifact-name", required=True)

    args = parser.parse_args(argv)
    github_output = os.environ.get("GITHUB_OUTPUT")
    destination = Path(github_output) if github_output else None
    try:
        if args.command == "capture":
            keys = capture(Path(args.raw), Path(args.capture))
            json.dump({"captured": keys}, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        if args.command == "gate":
            report = gate(Path(args.capture))
            payload = report.to_json()
            Path(args.report).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            json.dump(payload, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0 if report.passed else 2
        outputs = seal(
            Path(args.report),
            Path(args.wheel),
            Path(args.sdist),
            Path(args.evidence_root),
            args.evidence_artifact_name,
        )
        write_github_output(outputs, destination)
        json.dump(outputs, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    except (GateError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
