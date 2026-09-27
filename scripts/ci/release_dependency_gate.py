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
import email.parser
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import urllib.parse
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import tomllib

try:
    from scripts.ci.spdx_license_policy import (
        LICENSE_MISSING,
        LICENSE_SELECTION_INVALID,
        LICENSE_TEXT_MISSING,
        LICENSE_TEXT_UNVERIFIED,
        LicenseDecision,
        evaluate_license_expression,
        recognize_license_text,
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
        LICENSE_SELECTION_INVALID,
        LICENSE_TEXT_MISSING,
        LICENSE_TEXT_UNVERIFIED,
        LicenseDecision,
        evaluate_license_expression,
        recognize_license_text,
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
LOCK_SOURCE_UNSUPPORTED = "LOCK_SOURCE_UNSUPPORTED"
LOCK_SOURCE_ORIGIN_DENIED = "LOCK_SOURCE_ORIGIN_DENIED"
LOCK_SOURCE_CREDENTIAL_IN_URL = "LOCK_SOURCE_CREDENTIAL_IN_URL"
LOCK_SOURCE_PATH_ESCAPE = "LOCK_SOURCE_PATH_ESCAPE"
SCOPE_UNVERIFIABLE = "SCOPE_UNVERIFIABLE"
SCOPE_SET_MISMATCH = "SCOPE_SET_MISMATCH"
STRIX_CREDENTIALS_ABSENT = "STRIX_CREDENTIALS_ABSENT"
STRIX_BINDING_MISSING = "STRIX_BINDING_MISSING"
STRIX_BINDING_MALFORMED = "STRIX_BINDING_MALFORMED"
STRIX_BINDING_UNBOUND = "STRIX_BINDING_UNBOUND"
STRIX_TEXTUAL_PASS_REJECTED = "STRIX_TEXTUAL_PASS_REJECTED"
STRIX_FINDINGS_OPEN = "STRIX_FINDINGS_OPEN"
STRIX_MATRIX_LIMIT = 256
# ponytail: two native matrices cover 512 fixtures; add another only if a real full set exceeds this.
STRIX_PLAN_LIMIT = 2 * STRIX_MATRIX_LIMIT
STRIX_MATRIX_OUTPUT_MAX_BYTES = 512 * 1024

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_NORMALIZE_RE = re.compile(r"[-_.]+")
_MAX_JSON_BYTES = 16 * 1024 * 1024
# A distribution's declared metadata header block; anything larger is refused
# rather than read, since it is adjudicated before the closure is installed.
_MAX_METADATA_BYTES = 4 * 1024 * 1024

CYCLONEDX_SCHEMA = "https://cyclonedx.org/schema/bom-1.7.schema.json"
CYCLONEDX_PREDICATE_TYPE = "https://cyclonedx.org/bom"
SOURCE_IDENTITY_FILENAME = "source-identity.json"
CHECKSUM_FILENAME = "checksums.sha256"
FILENAME_PROPERTY = "cwl:artifact:filename"

# The two stages of one release gate. ``license`` enumerates the full dependency
# scope and applies license/evidence policy with no provider credential present,
# so a denied or unverifiable licence is refused before any model path is
# reached. ``full`` additionally requires the machine-readable Strix binding.
# Only a ``full`` report may be sealed, so a passing prescreen can never stand in
# for the Strix stage.
LICENSE_STAGE = "license"
FULL_STAGE = "full"
GATE_STAGES = (LICENSE_STAGE, FULL_STAGE)

# The ecosystems whose resolved scope this gate can establish. An ecosystem
# outside this set is SCOPE_UNVERIFIABLE rather than silently skipped: CO#1226
# treated coverage as satisfied because one component of one ecosystem existed.
SUPPORTED_ECOSYSTEMS = {"python": "pypi", "cargo": "cargo"}

# The provider credentials the Strix stage requires. They are declared optional
# on the reusable workflow so the licence stage can run without them; reaching
# the Strix stage without them is a fail-closed refusal, never a skip.
STRIX_CREDENTIAL_NAMES = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)

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

WINDOWS_SYSTEM_DLLS = {
    "ADVAPI32.DLL", "BCRYPT.DLL", "BCRYPTPRIMITIVES.DLL", "COMBASE.DLL",
    "CRYPT32.DLL", "GDI32.DLL", "KERNEL32.DLL", "MSVCRT.DLL", "NTDLL.DLL",
    "OLE32.DLL", "OLEAUT32.DLL", "SECUR32.DLL", "SHELL32.DLL", "SHLWAPI.DLL",
    "UCRTBASE.DLL", "USER32.DLL", "USERENV.DLL", "VERSION.DLL", "WINMM.DLL",
    "WS2_32.DLL",
}
MAC_FRAMEWORK = re.compile(
    r"/System/Library/Frameworks/([A-Za-z][A-Za-z0-9]*)\.framework/"
    r"Versions/[A-Za-z0-9]+/\1\Z"
)
MAC_SYSTEM_DYLIB = re.compile(r"/usr/lib/lib[A-Za-z0-9._+-]+\.dylib\Z")
WINDOWS_API_SET = re.compile(r"(?:api|ext)-ms-win-[a-z0-9-]+\.dll\Z", re.IGNORECASE)

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
    lock_sha256: str = ""
    license_selections_sha256: str = ""
    stage: str = FULL_STAGE
    scopes: list[dict[str, Any]] = field(default_factory=list)
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
            "stage": self.stage,
            "strix_evidence_binder_sha256": self.binder_sha256,
            # The install step may only install the artifacts this verdict judged,
            # from the lock this verdict read; both are bound here by digest.
            "python_lock_sha256": self.lock_sha256,
            "license_selections_sha256": self.license_selections_sha256,
            "scopes": sorted(self.scopes, key=lambda row: row["ecosystem"]),
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
# Lock source directives: parse, validate, then use
# ---------------------------------------------------------------------------
#
# `pip install -r <lock>` reads the real lock and honors any `--index-url`,
# `--extra-index-url` or `--find-links` in it. The capture step's `pip download`
# used a reconstructed plain requirements file that silently dropped every
# `-`-prefixed directive, so install and collection could resolve from different
# sources — and a lock using a private or extra index failed capture outright.
#
# The fix is not to forward what the lock says. Every directive is parsed,
# validated against the same trusted-origin and bounded-path policy
# `materialize_base_python_requirements.py` already applies, and only then turned
# into an explicit option list. An unlisted origin, a non-HTTPS scheme, a URL
# carrying userinfo, a path escaping the permitted root, and any directive form
# outside the supported set are each a hard failure. Nothing is dropped silently:
# silent dropping was the defect.
#
# The supported dialect is deliberately narrow, and this organization's own
# `requirements-*-hashes.txt` files use none of these forms today. Nested includes
# (`-r`/`-c`) and environment markers are rejected rather than reimplemented,
# because honoring them would require a second requirements dialect and would let
# install and download disagree about which distributions exist.

ALLOWED_INDEX_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
_INDEX_DIRECTIVES = {"-i", "--index-url", "--extra-index-url"}
_FIND_LINKS_DIRECTIVES = {"-f", "--find-links"}
_NESTED_INCLUDE_DIRECTIVES = {"-r", "--requirement", "-c", "--constraint"}
# The same rejected characters `_bounded_requirement_include_target` uses.
_UNSAFE_PATH_CHARACTERS = ("\\", ":", "?", "#")


def _require_trusted_index_origin(directive: str, url: str) -> None:
    """Require an HTTPS, default-port, host-allowlisted index URL with no userinfo.

    This mirrors ``materialize_base_python_requirements._is_trusted_uv_https_host``.
    No failure detail includes the URL, its query, or its host when userinfo is
    present, so credential material cannot reach a log or the gate report through
    a refusal message.
    """

    parsed = urllib.parse.urlparse(url)
    if parsed.username is not None or parsed.password is not None:
        raise GateError(
            LOCK_SOURCE_CREDENTIAL_IN_URL,
            f"{directive} carries userinfo credentials; the URL is withheld from this "
            "message and from the gate report",
        )
    try:
        default_port = parsed.port in (None, 443)
    except ValueError:
        default_port = False
    if parsed.scheme != "https" or not default_port:
        raise GateError(
            LOCK_SOURCE_ORIGIN_DENIED,
            f"{directive} must use HTTPS on the default port",
        )
    if parsed.hostname not in ALLOWED_INDEX_HOSTS:
        raise GateError(
            LOCK_SOURCE_ORIGIN_DENIED,
            f"{directive} names host {parsed.hostname!r}, which is not an allowed "
            "package index origin",
        )


def _resolve_bounded_find_links(directive: str, target: str, root: Path) -> Path:
    """Resolve a `--find-links` directory, requiring it to stay inside ``root``.

    The relative-path rules are the ones
    ``materialize_base_python_requirements._bounded_requirement_include_target``
    applies to a bounded include: normalized, relative, no ``.`` or ``..`` part,
    and none of the unsafe characters. A URL-valued ``--find-links`` is refused
    outright, so this directive can never reach the network.
    """

    if target.startswith(("-", "~")) or any(
        character in target for character in _UNSAFE_PATH_CHARACTERS
    ):
        raise GateError(
            LOCK_SOURCE_PATH_ESCAPE,
            f"{directive} target is not a safe relative directory path",
        )
    candidate = PurePosixPath(target)
    if (
        not candidate.parts
        or target != candidate.as_posix()
        or candidate.is_absolute()
        or "." in candidate.parts
        or ".." in candidate.parts
    ):
        raise GateError(
            LOCK_SOURCE_PATH_ESCAPE,
            f"{directive} target must be a normalized relative path inside the release tree",
        )
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise GateError(
            LOCK_SOURCE_PATH_ESCAPE,
            f"{directive} target escapes the permitted release root",
        )
    if resolved.is_symlink() or not resolved.is_dir():
        raise GateError(
            LOCK_SOURCE_PATH_ESCAPE,
            f"{directive} target is not a regular directory inside the release tree",
        )
    return resolved


def _split_directive(line: str) -> tuple[str, list[str]]:
    """Split one directive line into its option name and its value fields.

    The value count is not judged here: an unsupported flag such as ``--no-index``
    legitimately carries no value, and reporting it as a value-count problem would
    hide the real reason it is refused.
    """

    if "=" in line.split(" ", 1)[0]:
        directive, _, value = line.partition("=")
        return directive.strip(), [value.strip()]
    fields = line.split()
    return fields[0], fields[1:]


def _single_value(directive: str, values: Sequence[str]) -> str:
    """Return the one value a supported source directive must carry."""

    if len(values) != 1 or not values[0]:
        raise GateError(
            LOCK_SOURCE_UNSUPPORTED,
            f"lock directive {directive!r} must carry exactly one value",
        )
    return values[0]


def lock_download_options(text: str, permitted_root: Path) -> list[str]:
    """Return the validated pip options that make download resolve like install.

    Raises ``GateError`` for every unsupported or untrusted form rather than
    dropping it, so capture can never resolve from a source install did not use.
    """

    joined = re.sub(r"\\\s*\n", " ", text)
    options: list[str] = []
    for raw in joined.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not line.startswith("-"):
            if ";" in line:
                raise GateError(
                    LOCK_SOURCE_UNSUPPORTED,
                    "environment markers are not supported: install and download could "
                    "disagree about which distributions exist",
                )
            continue
        if line.startswith("--hash="):
            continue
        directive, values = _split_directive(line)
        if directive in _NESTED_INCLUDE_DIRECTIVES:
            raise GateError(
                LOCK_SOURCE_UNSUPPORTED,
                f"{directive} includes are not supported; inline the closure into one "
                "hash-pinned lock",
            )
        if directive in _INDEX_DIRECTIVES:
            value = _single_value(directive, values)
            _require_trusted_index_origin(directive, value)
            options.extend([directive, value])
            continue
        if directive in _FIND_LINKS_DIRECTIVES:
            resolved = _resolve_bounded_find_links(
                directive, _single_value(directive, values), permitted_root
            )
            options.extend([directive, str(resolved)])
            continue
        raise GateError(
            LOCK_SOURCE_UNSUPPORTED,
            f"lock directive {directive!r} is not a supported source form",
        )
    return options


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
        if graph[entry].get("source") is not None and lock[entry] is None:
            failures.append(
                Failure(
                    CARGO_CHECKSUM_MISSING,
                    f"cargo/{entry[0]}@{entry[1]}",
                    "sourced dependency has no Cargo.lock checksum",
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


def classify_platform_link(name: str, target: str, leg: str, member: str) -> dict[str, str] | None:
    """Review an external platform link; unknown links need separate licence evidence."""
    kind = ""
    basis = ""
    if "linux" in target:
        runtime = classify_soname(name)
        if runtime is not None:
            kind, basis = "system-runtime", f"{runtime[0]}; {runtime[1]}"
    elif "darwin" in target:
        if MAC_FRAMEWORK.fullmatch(name) or MAC_SYSTEM_DYLIB.fullmatch(name):
            kind, basis = "system-runtime", "Apple-provided /System/Library/Frameworks or /usr/lib"
        elif (member.startswith("fast_mlsirm/_core.")
              and name == f"@rpath/fast_mlsirm.{PurePosixPath(member).name}"):
            kind, basis = "self-install-name", "the inspected extension itself"
    elif "windows" in target:
        normalized = name.upper()
        py_version = leg.rsplit("-py", 1)[1].replace(".", "")
        if WINDOWS_API_SET.fullmatch(name):
            kind, basis = "system-runtime", "Windows API-set loader contract"
        elif normalized in WINDOWS_SYSTEM_DLLS:
            kind, basis = "system-runtime", "Windows operating-system DLL"
        elif normalized == f"PYTHON{py_version}.DLL":
            kind, basis = "interpreter-runtime", "CPython runtime required by this wheel tag"
        elif normalized in {"VCRUNTIME140.DLL", "VCRUNTIME140_1.DLL"}:
            kind, basis = "external-runtime", "Visual C++ runtime is linked, not bundled"
    return {"name": name, "kind": kind, "basis": basis} if kind else None


def evaluate_native_links(
    evidence: Mapping[str, Any], subject: str, *, target: str = "", leg: str = ""
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
        origin = library.get("path")
        if (not isinstance(origin, str) or not origin
                or not isinstance(library.get("needed"), list)
                or not isinstance(library.get("static_archives"), list)):
            raise GateError(
                EVIDENCE_INCOMPLETE,
                f"{subject}: native library has no complete link inventory",
            )
        for soname in _require_list(library, "needed", subject):
            platform = classify_platform_link(str(soname), target, leg, origin) if target else None
            if platform is not None:
                properties.append({"name": f"cwl:native:{platform['kind']}",
                                   "value": f"{soname}={platform['basis']}"})
                continue
            allowlisted = classify_soname(str(soname)) if not target else None
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


def _declared_identifiers(expression: str) -> frozenset[str]:
    """Return the bare SPDX identifiers a declared expression names.

    Only identifiers are compared, so operators, parentheses and ``WITH``
    exceptions cannot make an unrelated text read as consistent.
    """

    tokens = re.split(r"[()\s]+", expression.replace("+", ""))
    reserved = {"AND", "OR", "WITH", ""}
    return frozenset(token for token in tokens if token.upper() not in reserved)


# Complete members from checksum-bound libm 0.2.16 (upstream dfd2203a).
# LICENSE.txt explicitly delegates retained third-party notices to src files.
# Full Sun/BSD notices were read and compared with SPDX SunPro/BSD-2-Clause;
# MIT SPDX source headers use the complete package MIT grant. No comment parser
# or source snippet classifies unknown files. The original crate is the fixture.
_LIBM_ARCHIVE_SHA256 = "b6d2cec3eae94f9f509c767b45932f1ada8350c4bdb85af2fcab4a3c14807981"
_LIBM_LICENSE_MEMBERS = {
    'libm-0.2.16/LICENSE.txt': ('3823dda7cf046602f4b4e77ec8e227863dc4736037cc85bb33d9f19febe16bb7', 'MIT'),
    'libm-0.2.16/src/math/acos.rs': ('efd83a6138061209867f06421c6a756b8ca3aab5c6c0a85c4aba31bedb299da5', 'SunPro'),
    'libm-0.2.16/src/math/acosf.rs': ('c5c9c74d267725bbe5f9319e6f4a396af6ce46c890b601d3f963a5d74d12e4c3', 'SunPro'),
    'libm-0.2.16/src/math/asin.rs': ('9693a7cb61674ec6fe22be9db8fe20276729c48b1562fd86d5421e372a0a12e4', 'SunPro'),
    'libm-0.2.16/src/math/asinf.rs': ('25f6b7bbf46fc5aac4ebdd9e00118239747dcd28a79b90b858ddc4633d773d65', 'SunPro'),
    'libm-0.2.16/src/math/atan.rs': ('54181dbddf4f77b90b32b9f6819ac989da570dc02b791f3685d20a23d51324be', 'SunPro'),
    'libm-0.2.16/src/math/atan2.rs': ('7d028d4d397f7484b8feed7b228eda65b84acac94d27729d236d5df95e38d8f0', 'SunPro'),
    'libm-0.2.16/src/math/atan2f.rs': ('b9497b5adb75e2788c404fd121aa64dcfa0e9357b67af3b3e7e6d4624dae1ca1', 'SunPro'),
    'libm-0.2.16/src/math/atanf.rs': ('197762f16ed5951236e17d0869c529e857acc329cc287df019ff69e5401f3b4d', 'SunPro'),
    'libm-0.2.16/src/math/cbrt.rs': ('1ed98a0943c46ca48e32af54b6baeb80b6e8da5dda550005711fcb26bfcf12c2', 'MIT'),
    'libm-0.2.16/src/math/cbrtf.rs': ('7a2b4f190e8618c52cb23b47c040a4b4eacca739c68393cf14fb3f5d73988127', 'SunPro'),
    'libm-0.2.16/src/math/cos.rs': ('6e81752899c471bd42d04bdf08e0b22bc10a29f92fa2a343281b995fd342f035', 'SunPro'),
    'libm-0.2.16/src/math/cosf.rs': ('f48aa954f199fe4f54fd73b4e7886a75f2c08afba7fc31c6a36db5b5f90ced69', 'SunPro'),
    'libm-0.2.16/src/math/erf.rs': ('5a69f440d5ca88a5c4a45119837c45b14238836a036675230e10fec41d293a3b', 'SunPro'),
    'libm-0.2.16/src/math/erff.rs': ('62c30876390e532d7dc9ac1f1f1c1f654065fba2b2e534e531964d79e1766196', 'SunPro'),
    'libm-0.2.16/src/math/exp.rs': ('1d486e847e1752fb9ce74a714096a11adcac935dacd4f17625ff63819103a80d', 'SunPro'),
    'libm-0.2.16/src/math/exp2.rs': ('e7270f15a682b69a49e042c80503c206d37c6c895f2c63da59a5e2431fa5fedc', 'BSD-2-Clause'),
    'libm-0.2.16/src/math/exp2f.rs': ('3b4b5cb2e5674e1ce66a6051710738c1a6edc1d1638686fe9c78f0af4792a634', 'BSD-2-Clause'),
    'libm-0.2.16/src/math/expf.rs': ('33b01180ebd01bb2911379476c5411fd05b066f2e17ef66e48c4dde83a7f01c0', 'SunPro'),
    'libm-0.2.16/src/math/expm1.rs': ('6cc612ca7cf1384dc15f541b301a1f176efbc79536aff1293408b3121cc30ad3', 'SunPro'),
    'libm-0.2.16/src/math/expm1f.rs': ('2b517f1bcb6279c906aad737f08c83ac30d7871e3beff266ea50a01fa18ccc81', 'SunPro'),
    'libm-0.2.16/src/math/fma.rs': ('16e72470f5c4407c44183cf06f5868f216c92e0532f3fb387b57dbccf815e2a7', 'MIT'),
    'libm-0.2.16/src/math/generic/ceil.rs': ('66b3def2b00ed9dd6a4f59c73765a050853dfe06c828fdf731987ac99e7c2a88', 'MIT'),
    'libm-0.2.16/src/math/generic/floor.rs': ('7d4f15369abefa27645d6deda51d30febbe60ee9dca76e72a9364d574d0711c0', 'MIT'),
    'libm-0.2.16/src/math/generic/fma.rs': ('ba44930a56d7c1953ab0c96c7c767911c9dc6967083700c8ef02f43672c8482f', 'MIT'),
    'libm-0.2.16/src/math/generic/fmax.rs': ('68d923950c3f1eab68baeab24679ab50918b663904839bc349ef666d9467518f', 'MIT'),
    'libm-0.2.16/src/math/generic/fmaximum.rs': ('c4b8b7080821a2dc65d0a50baf717ccd9ee20b813ce6d6d3f9f01b5700b674fa', 'MIT'),
    'libm-0.2.16/src/math/generic/fmaximum_num.rs': ('2f2d41e1f0160eb73469fa63db27d881b5b8eabc6d62fae7ca1b4b03eb35c5d5', 'MIT'),
    'libm-0.2.16/src/math/generic/fmin.rs': ('9bbdece9606e5eac57f3a91a5db7aab814c8e2b28b6df1813723c6b5715efc55', 'MIT'),
    'libm-0.2.16/src/math/generic/fminimum.rs': ('a6a33085356610eced23957ca86456b7dbe95e0f9d916298d59ce8bd90076b02', 'MIT'),
    'libm-0.2.16/src/math/generic/fminimum_num.rs': ('f5db65654e690adea16da83839d62a707cc814c998fd4a77e63caaaea1472256', 'MIT'),
    'libm-0.2.16/src/math/generic/fmod.rs': ('11aae62d08d656d815184eafd78a3b2d5764b6ce308b89e3819cd049bc491fe7', 'MIT'),
    'libm-0.2.16/src/math/generic/rint.rs': ('deec183fd0da6c0a47ab272a256990cea4f9231db7faff314697886457d6841a', 'MIT'),
    'libm-0.2.16/src/math/generic/sqrt.rs': ('c58e48ec07404d618109ad45332efe46c5246f42a2ddefdf5b25ba19e4ca9a0f', 'MIT'),
    'libm-0.2.16/src/math/generic/trunc.rs': ('46dd2cc35f6da25099ea2202264d8da3330b5ff1a962a8afb671b54b6ef6002d', 'MIT'),
    'libm-0.2.16/src/math/j0.rs': ('1cb991f0151a626744ad1832d4aedfaca681bcfcecc797de5ac5e9baf2342006', 'SunPro'),
    'libm-0.2.16/src/math/j0f.rs': ('de97374b6a0019fd8b3d1f553be1708018546491d3b4a5fc650ee2dcdfc9620e', 'SunPro'),
    'libm-0.2.16/src/math/j1.rs': ('e0a10746fd11a458d55ee61e758d9f016ff0f2203a07eb9907b5aca709a40469', 'SunPro'),
    'libm-0.2.16/src/math/j1f.rs': ('27b586c94d510aa653923b6b83cfec174e1f5da326d9120b0a0135b1190e32dc', 'SunPro'),
    'libm-0.2.16/src/math/jn.rs': ('ba36d25d4bbada83aadb3b2986879b7d88b91adb7b502061d21bf96ff3942194', 'SunPro'),
    'libm-0.2.16/src/math/jnf.rs': ('b3861e19644ae669fe17db81d91aeaee9c9f9051b59957ab674017684c98fe32', 'SunPro'),
    'libm-0.2.16/src/math/k_cos.rs': ('d4867527877c846aa8e2a0b43cf06f03e2d94c321a548acaf8d5171c09ff4057', 'SunPro'),
    'libm-0.2.16/src/math/k_cosf.rs': ('8f76089d014e217b96c9eca520271e64d467dc0d6542bf313dd70eb96c040f7f', 'SunPro'),
    'libm-0.2.16/src/math/k_sin.rs': ('dfe6524cb2d530ec51eb1a2ab233aeb65b3f12177c1fb2f50f044ea41170f5d8', 'SunPro'),
    'libm-0.2.16/src/math/k_sinf.rs': ('cf0e8bbe8d73a6704b7f1f710f5b9d31f190f1c633e894d4f69c4e3bc359eba3', 'SunPro'),
    'libm-0.2.16/src/math/k_tan.rs': ('dc3f8ece9187bbd65792a7d1068e676092e9c2a0886f28c80579f9bd94d744b7', 'SunPro'),
    'libm-0.2.16/src/math/k_tanf.rs': ('3381d2d4865bfc98e87aadb96bd8986f7691a389569a58fb1cb8db74fb5d9c20', 'SunPro'),
    'libm-0.2.16/src/math/lgamma_r.rs': ('5d56169c077b5b9f88902e2d243a7a4b4d06b89295aa84283d6fa15d9c244032', 'SunPro'),
    'libm-0.2.16/src/math/lgammaf_r.rs': ('0bc2b5e0eec7666973adaca536f4d5fe978c8793bb340484fff9e5e7abb425f0', 'SunPro'),
    'libm-0.2.16/src/math/log.rs': ('df5f4d1325e89621bfcd9cf7788d0d7e20a6ef7f429110fe35b370b3c9362615', 'SunPro'),
    'libm-0.2.16/src/math/log10.rs': ('4a96dd2b6a2a505497f2bb7ea956a50491d068dab1b6055a573aec1724a52e40', 'SunPro'),
    'libm-0.2.16/src/math/log10f.rs': ('784a576dd4a4071f4f67c670eb9b221cb03014818c4b2d71afbcbd2211431caf', 'SunPro'),
    'libm-0.2.16/src/math/log1p.rs': ('bb8ce741e54d8f001d9c12450a14a663bd413014da2ade9ba1f5fbc9ff0c9a88', 'SunPro'),
    'libm-0.2.16/src/math/log1pf.rs': ('8736222a9b9004b061f1339bb819c63c6b54414d4a01ef79d5f5a5f0a70677b5', 'SunPro'),
    'libm-0.2.16/src/math/log2.rs': ('1ec0cdd94bf4435ff0402d209089b1bdbcb1ba9a4cd5f77807f9c84cf534f980', 'SunPro'),
    'libm-0.2.16/src/math/log2f.rs': ('7b3b17ba08df6b5a57dacf6f945bfe1a3c088bee0eb11e201ac5affc7f65925a', 'SunPro'),
    'libm-0.2.16/src/math/logf.rs': ('c7dfa5e89fcca0411624fdc594f64c62d5dfa3b91f061fcb7ac3aea18414f238', 'SunPro'),
    'libm-0.2.16/src/math/pow.rs': ('c5566d0f48682d107e8803b0ed204ff3521503348f18a4f26cbe3f47fef15192', 'SunPro'),
    'libm-0.2.16/src/math/powf.rs': ('819971cb8e927d80113aded3cfe90dcd501c031e0eb1c562b58842fddd1751be', 'SunPro'),
    'libm-0.2.16/src/math/rem_pio2.rs': ('5a040ab09dc356bca6d57712327151ed43003e2bac156553e3eb87d1cdefd2d1', 'SunPro'),
    'libm-0.2.16/src/math/rem_pio2_large.rs': ('986b5b9ad2c8fba828aee47bf198eab97fab243359ab03eb09783d98ca5847b5', 'SunPro'),
    'libm-0.2.16/src/math/rem_pio2f.rs': ('fb34bab63f8d143dfefa4ef2e31e8166bf21f3c67f1519bfc3ca4fb8eb28cafe', 'SunPro'),
    'libm-0.2.16/src/math/sin.rs': ('b48cebd120fc2ac93a6563059cabda28a72c8680304eb8335b92b412235cc232', 'SunPro'),
    'libm-0.2.16/src/math/sincos.rs': ('a9c414e828c2e78b6bce4d5e4237b1baa93e81d78421aed5cedeab43df64067f', 'SunPro'),
    'libm-0.2.16/src/math/sincosf.rs': ('c39b6e3b52be83ccf4015ff105dab55e693577ebfc43745881750e73eebc6fa6', 'SunPro'),
    'libm-0.2.16/src/math/sinf.rs': ('b17db34d5da39a0f336d831abcb700fab69402c915321823870f1845e66c03d2', 'SunPro'),
    'libm-0.2.16/src/math/support/int_traits/narrowing_div.rs': ('5f5378e33f1da56090d0dce2514926ab465dce65b89ad4ee2f7da07a92f8d5de', 'MIT'),
    'libm-0.2.16/src/math/support/modular.rs': ('cf6a562d6bdf16336f31d41c59e828ad47f85388849d20d6d3b59fc1c3e388a2', 'MIT'),
    'libm-0.2.16/src/math/tan.rs': ('2ea87ca18526753db6d149635ed6c895c8fbafd1e0fa7a9c04f7dc44b4eae986', 'SunPro'),
    'libm-0.2.16/src/math/tanf.rs': ('f7140c4193a57709acde5d290c8f83435562da42924c54cab0aa3a4f26095190', 'SunPro'),
}


def evaluate_dependency_license(
    evidence: Mapping[str, Any],
    subject: str,
    selection: Mapping[str, str] | None,
) -> tuple[list[Failure], LicenseDecision, str]:
    """Decide one dependency's license from metadata and bundled license text."""

    expression, source = declared_license_expression(evidence)
    # Cargo Book, manifest licence fields and footnote 1:
    # https://doc.rust-lang.org/cargo/reference/manifest.html#the-license-and-license-file-fields
    # Only this reviewed legacy pair is adapted; SPDX parsing remains strict.
    if evidence.get("ecosystem") == "cargo" and expression in {
        "MIT/Apache-2.0", "Apache-2.0/MIT", "Apache-2.0 / MIT"
    }:
        expression = "MIT OR Apache-2.0"
        source = "Cargo legacy licence pair"
    # This exact crate bundles Unicode tables under an independent full grant.
    # Cargo's main-code declaration must not erase the Unicode notice obligation.
    # https://spdx.org/licenses/Unicode-DFS-2016.html (full text read).
    if (evidence.get("ecosystem") == "cargo" and subject == "cargo/regex-syntax@0.8.11"
            and evidence.get("source_sha256") == "d6f6ff9a378485b298a5286656da665ba74413d36db0979633275d2e708145d4"
            and expression == "MIT OR Apache-2.0"):
        expression = "(MIT OR Apache-2.0) AND Unicode-DFS-2016"
        source = "Cargo declaration plus exact archived Unicode data grant"
    libm_scope = (evidence.get("ecosystem") == "cargo" and subject == "cargo/libm@0.2.16"
                  and evidence.get("source_sha256") == _LIBM_ARCHIVE_SHA256 and expression == "MIT")
    if libm_scope:
        expression = "MIT AND BSD-2-Clause AND SunPro"
        source = "Cargo declaration plus exact archived file-specific grants"
    spirv_scope = (evidence.get("ecosystem") == "cargo"
                   and subject == "cargo/spirv@0.4.0+sdk-1.4.341.0"
                   and evidence.get("source_sha256") == "d9571ea910ebd84c86af4b3ed27f9dbdc6ad06f17c5f96146b2b671e2976744f"
                   and expression == "Apache-2.0")
    if spirv_scope:
        # Exact upstream generator consumes core and all 15 extension grammars.
        # Khronos LICENSE explicitly covers every JSON; retain original input
        # notices (including Arm's MIT markers) without relabeling those markers.
        expression = "Apache-2.0 AND MIT-Khronos-old"
        source = "Cargo declaration plus exact generated-input grant scope"
    decision = evaluate_license_expression(
        expression,
        selection=(selection or {}).get("chosen"),
        rationale=(selection or {}).get("rationale"),
    )
    failures: list[Failure] = []
    if ((libm_scope or spirv_scope or source == "Cargo declaration plus exact archived Unicode data grant")
            and decision.allowed and (selection or {}).get("chosen") != decision.selected):
        failures.append(Failure(LICENSE_SELECTION_INVALID, subject,
                                "selection must explicitly retain every independent third-party obligation"))
    if not decision.allowed:
        failures.append(Failure(decision.code, subject, decision.detail))
    texts = _require_mapping(evidence, "license_texts", subject)
    if not texts:
        # A permissive declaration is a claim by the publisher, not evidence. With no
        # bundled text there is nothing to check it against, so the release cannot be
        # cleared on the claim alone.
        failures.append(
            Failure(
                LICENSE_TEXT_MISSING,
                subject,
                f"declared {expression} but the distribution bundles no license text",
            )
        )
    recognized_texts = {name: recognize_license_text(str(text)) for name, text in texts.items()}
    if libm_scope:
        for name, (digest, identifier) in _LIBM_LICENSE_MEMBERS.items():
            text = texts.get(name)
            if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
                failures.append(Failure(LICENSE_TEXT_UNVERIFIED, subject,
                                        f"reviewed file-specific licence member missing or changed: {name}"))
            else:
                recognized_texts[name] = frozenset({identifier})
    grants = frozenset().union(*(ids for ids in recognized_texts.values() if ids is not None))
    for filename in sorted(texts):
        recognized = recognized_texts[filename]
        # Exact reference notices from checksum-verified memchr 2.8.3,
        # termcolor 1.4.1, winapi-util 0.1.11 and typenum 1.20.1.
        # A reference is never a grant; every named full grant must be present.
        normalized = re.sub(r"[ \t\r\n]+", " ", str(texts[filename])).strip(" \t\r\n")
        references = {
            "7e7a2c785f3db52a3daf64a62b76b09b940355e4fe1b7f7092f473b7663416b1": frozenset({"MIT", "Unlicense"}),
            "db11fec9946737df39ca3898d9cd8c10ec6f6c3a884a6802b0ad0b81b4e8f23a": frozenset({"MIT", "Apache-2.0"}),
        }.get(hashlib.sha256(normalized.encode()).hexdigest())
        if evidence.get("ecosystem") == "cargo" and references is not None and references <= grants:
            recognized = references
        # Reviewed android_system_properties 0.1.5/0.1.6 Apache application notice:
        # https://www.apache.org/licenses/LICENSE-2.0.txt (Appendix).
        # Recognize the notice only beside a complete independently granted MIT
        # alternative. It never enters `grants`, so choosing Apache still needs
        # the complete Apache terms rather than this link and disclaimer.
        if (evidence.get("ecosystem") == "cargo"
                and hashlib.sha256(normalized.encode()).hexdigest() == "ce03197ac0bc9c47f5b54e363c8832966483f167792f63e61bc2f3a7e1f4c953"
                and expression in {"MIT OR Apache-2.0", "Apache-2.0 OR MIT"}
                and "MIT" in grants):
            recognized = frozenset({"Apache-2.0"})
        # unarray 0.1.4 README at 0151bf12 explicitly offers the Apache option.
        # Its checksum binds that README and the unchanged MIT template. Accept
        # the unselected template as a reference only; never add it to grants.
        if (evidence.get("ecosystem") == "cargo" and subject == "cargo/unarray@0.1.4"
                and evidence.get("source_sha256") == "eaea85b334db583fe3274d12b4cd1880032beab409c0d774be044d4480ab9a94"
                and filename == "unarray-0.1.4/LICENSE-MIT"
                and hashlib.sha256(normalized.encode()).hexdigest() == "c6c34df041f56fa49263c56da640381fc52cc1d86dfa95a99f2fe8a7b83e2137"
                and expression == "MIT OR Apache-2.0"
                and decision.allowed and decision.selected == "Apache-2.0"
                and "Apache-2.0" in grants):
            recognized = frozenset({"MIT"})
        code = scan_license_text(str(texts[filename]))
        if code is None and decision.allowed:
            if recognized is None:
                # Neither a denied title nor any recognizable license: an `UNKNOWN`
                # body, a commercial-redistribution restriction, or arbitrary prose
                # all land here and must fail rather than pass by default.
                failures.append(
                    Failure(
                        LICENSE_TEXT_UNVERIFIED,
                        subject,
                        f"bundled {filename} matches no recognized license text",
                    )
                )
            elif not (recognized & _declared_identifiers(expression)):
                failures.append(
                    Failure(
                        LICENSE_TEXT_DISAGREEMENT,
                        subject,
                        f"declared {expression} but bundled {filename} is "
                        f"{'/'.join(sorted(recognized))} text",
                    )
                )
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
    if decision.allowed and texts and not any(f.code == LICENSE_TEXT_UNVERIFIED for f in failures):
        effective = re.sub(r"\bWITH\s+[A-Za-z0-9.+-]+", "", decision.selected)
        missing = _declared_identifiers(effective) - grants
        if missing:
            failures.append(Failure(LICENSE_TEXT_MISSING, subject,
                                    f"selected obligations lack full grant texts: {sorted(missing)}"))
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
    *, fixture_key: str | None = None,
) -> list[Failure]:
    """Require a well-formed machine-readable Strix binding; text never passes."""

    subject = fixture_key or dependency.key
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
        if fixture.get("id") != subject or fixture.get("sha256") != digest:
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


def read_archive_snapshot(path: Path) -> bytes:
    """Read one bounded regular archive once; reject a final symlink/race."""
    limit = 256 * 1024 * 1024
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise GateError(CAPTURE_INCOMPLETE, "archive is not a regular file")
            raw = stream.read(limit + 1)
    except OSError as error:
        raise GateError(CAPTURE_INCOMPLETE, "captured archive is missing or unreadable") from error
    if len(raw) > limit:
        raise GateError(CAPTURE_INCOMPLETE, "archive exceeds the bounded read")
    return raw


def archive_license_evidence(raw: bytes, ecosystem: str) -> dict[str, Any]:
    """Hash and read all license members from the same immutable byte snapshot.

    No extraction or dependency code execution occurs. Repeated/path-ambiguous
    members and archive links are refused before any member is trusted. Custom
    declared license-file paths are included, not just conventional basenames.
    """
    texts: dict[str, str] = {}
    hashes: dict[str, str] = {}
    members: list[dict[str, str]] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw)) if ecosystem == "pypi" else tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
        with archive:
            entries = archive.infolist() if ecosystem == "pypi" else archive.getmembers()
            if len(entries) > 10000:
                raise GateError(CAPTURE_INCOMPLETE, "archive has too many members")
            files: dict[str, Any] = {}
            seen: set[str] = set()
            for entry in entries:
                name = entry.filename if ecosystem == "pypi" else entry.name
                path = PurePosixPath(name)
                canonical = str(path)
                if (not name or "\\" in name or "\x00" in name or path.is_absolute()
                        or ".." in path.parts or canonical in seen):
                    raise GateError(ARCHIVE_PATH_ESCAPE, "duplicate or unsafe archive member")
                seen.add(canonical)
                directory = entry.is_dir() if ecosystem == "pypi" else entry.isdir()
                link = stat.S_ISLNK(entry.external_attr >> 16) if ecosystem == "pypi" else not (entry.isfile() or entry.isdir())
                if link:
                    raise GateError(ARCHIVE_PATH_ESCAPE, "archive links/special members are unsupported")
                members.append({"type": "directory" if directory else "file", "name": name, "linkname": ""})
                if not directory:
                    files[canonical] = entry

            def read_member(name: str) -> bytes:
                """Read a bounded member from this already-open snapshot."""
                entry = files.get(name)
                if entry is None:
                    raise GateError(CAPTURE_INCOMPLETE, "declared license member is absent")
                size = entry.file_size if ecosystem == "pypi" else entry.size
                if size > _MAX_METADATA_BYTES:
                    raise GateError(CAPTURE_INCOMPLETE, "archive text member is oversized")
                handle = archive.open(entry) if ecosystem == "pypi" else archive.extractfile(entry)
                with handle:
                    data = handle.read(_MAX_METADATA_BYTES + 1)
                return data

            selected = {name for name in files if PurePosixPath(name).name.upper().startswith(
                ("LICENSE", "LICENCE", "COPYING", "NOTICE", "UNLICENSE"))}
            # AUTHORS can contain grants (r-efi), not just contributor names.
            inspected = 0
            for name in files:
                if PurePosixPath(name).name.upper().split(".", 1)[0] not in {"AUTHORS", "COPYRIGHT"}:
                    continue
                data = read_member(name)
                inspected += len(data)
                if inspected > _MAX_JSON_BYTES:
                    raise GateError(CAPTURE_INCOMPLETE, "attribution text set exceeds bounded read")
                if re.search(rb"\b(?:licen[cs]e|copyright|permission|redistribution)\b", data, re.IGNORECASE):
                    selected.add(name)
            if ecosystem == "pypi":
                metadata_paths = [name for name in files if name.endswith(".dist-info/METADATA")]
                for metadata_path in metadata_paths:
                    message = email.parser.BytesParser().parsebytes(read_member(metadata_path))
                    parent = PurePosixPath(metadata_path).parent
                    for declared in message.get_all("License-File", []):
                        declaration = PurePosixPath(declared)
                        if declaration.is_absolute() or ".." in declaration.parts or "\\" in declared:
                            raise GateError(ARCHIVE_PATH_ESCAPE, "unsafe declared license path")
                        candidates = {str(parent / declaration), str(parent / "licenses" / declaration)} & files.keys()
                        if not candidates:
                            raise GateError(CAPTURE_INCOMPLETE, "declared license member is absent")
                        selected.update(candidates)
            else:
                for manifest in (name for name in files if name.count("/") == 1 and name.endswith("/Cargo.toml")):
                    package = tomllib.loads(read_member(manifest).decode("utf-8")).get("package", {})
                    declared = package.get("license-file")
                    if declared:
                        declaration = PurePosixPath(declared)
                        if declaration.is_absolute() or ".." in declaration.parts or "\\" in declared:
                            raise GateError(ARCHIVE_PATH_ESCAPE, "unsafe declared license path")
                        selected.add(str(PurePosixPath(manifest).parent / declaration))
            if ecosystem == "cargo" and hashlib.sha256(raw).hexdigest() == _LIBM_ARCHIVE_SHA256:
                selected.update(_LIBM_LICENSE_MEMBERS)
            total = 0
            for name in sorted(selected):
                data = read_member(name)
                total += len(data)
                if total > _MAX_JSON_BYTES:
                    raise GateError(CAPTURE_INCOMPLETE, "license text set exceeds bounded read")
                texts[name] = data.decode("utf-8")
                hashes[name] = hashlib.sha256(data).hexdigest()
    except GateError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError, zipfile.BadZipFile, tarfile.TarError, UnicodeError) as error:
        raise GateError(CAPTURE_INCOMPLETE, "archive or license text cannot be decoded") from error
    return {"source_sha256": hashlib.sha256(raw).hexdigest(), "license_texts": texts,
            "license_member_sha256": hashes, "archive_members": members}


def _optional_text(path: Path) -> str | None:
    """Return one optional raw capture file's text, or ``None`` when absent."""

    if path.is_symlink() or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def build_evidence(raw_dir: Path, *, archive_bytes: bytes | None = None) -> tuple[Dependency, dict[str, Any]]:
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
    snapshot = read_archive_snapshot(raw_dir / "source.archive") if archive_bytes is None else archive_bytes
    bound = archive_license_evidence(snapshot, ecosystem)
    if source_sha256 != bound["source_sha256"]:
        raise GateError(SOURCE_HASH_MISMATCH, "raw archive does not match recorded source hash")
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
        "license_texts": bound["license_texts"],
        "license_member_sha256": bound["license_member_sha256"],
        "install_hook_sources": _read_text_files(raw_dir / "hooks"),
        "archive_members": bound["archive_members"],
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
    archive_dir = capture_root / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    if archive_dir.is_symlink():
        raise GateError(CAPTURE_INCOMPLETE, "archive destination must not be a symlink")
    written: list[str] = []
    for child in sorted(raw_root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            raise GateError(CAPTURE_INCOMPLETE, f"raw capture entry is not a directory: {child}")
        snapshot = read_archive_snapshot(child / "source.archive")
        dependency, evidence = build_evidence(child, archive_bytes=snapshot)
        destination = archive_dir / f"{dependency.slug}.archive"
        if destination.is_symlink():
            raise GateError(CAPTURE_INCOMPLETE, "archive destination must not be a symlink")
        destination.write_bytes(snapshot)
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


def capture_license_selections(source: Path, source_sha: str, capture: Path) -> None:
    """Copy only a regular selection blob from the exact release commit."""
    if not GIT_SHA_RE.fullmatch(source_sha):
        raise GateError(CAPTURE_INCOMPLETE, "selection source must be an exact commit SHA")
    path = "docs/release-license-selections.json"
    entry = subprocess.check_output(
        ["git", "ls-tree", source_sha, "--", path], cwd=source, text=True
    ).strip()
    destination = capture / "license-selections.json"
    if destination.exists() or destination.is_symlink():
        raise GateError(CAPTURE_INCOMPLETE, "selection destination already exists")
    if not entry:
        return  # No selection is still refused when an OR licence is encountered.
    if not entry.startswith("100644 blob "):
        raise GateError(CAPTURE_INCOMPLETE, "selection source must be a regular Git blob")
    blob_oid = entry.split()[2]
    size = int(subprocess.check_output(["git", "cat-file", "-s", blob_oid], cwd=source))
    if size > _MAX_METADATA_BYTES:
        raise GateError(CAPTURE_INCOMPLETE, "selection source exceeds bounded size")
    payload = subprocess.check_output(["git", "cat-file", "blob", blob_oid], cwd=source)
    if len(payload) > _MAX_METADATA_BYTES:
        raise GateError(CAPTURE_INCOMPLETE, "selection source exceeds bounded size")
    capture.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    _load_selections(capture)


def _load_selections(capture: Path) -> dict[str, Mapping[str, str]]:
    """Load optional dual-license selections, keyed by dependency identity."""

    path = capture / "license-selections.json"
    if not path.exists() and not path.is_symlink():
        return {}
    _require_regular_file(path, CAPTURE_INCOMPLETE)
    payload = load_json(path)
    if not isinstance(payload, list):
        raise GateError(CAPTURE_INCOMPLETE, "license-selections.json must be a JSON array")
    selections: dict[str, Mapping[str, str]] = {}
    for item in payload:
        if not isinstance(item, Mapping):
            raise GateError(CAPTURE_INCOMPLETE, "license selection entry must be an object")
        required = {"ecosystem", "name", "version", "chosen", "rationale"}
        if not required.issubset(item) or any(
            not isinstance(item[field], str) or not item[field].strip() for field in required
        ):
            raise GateError(
                CAPTURE_INCOMPLETE,
                f"license selection must declare {sorted(required)}",
            )
        key = f"{item['ecosystem']}/{item['name']}@{item['version']}"
        if key in selections:
            raise GateError(CAPTURE_INCOMPLETE, f"duplicate license selection: {key}")
        selections[key] = {"chosen": str(item["chosen"]), "rationale": str(item["rationale"])}
    return selections


def _enumerate_python(capture: Path) -> tuple[list[Dependency], list[Failure], set[str]]:
    """Enumerate Python dependencies, returning the lock's full expected key set."""

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
    # The lock is the producer's own declaration of the complete closure, so it —
    # not the subset that happened to resolve — is the expected set the collected
    # evidence is compared against.
    expected = {f"pypi/{name}@{version}" for (name, version) in lock}
    return dependencies, failures, expected


def _enumerate_cargo(capture: Path, *, source_root: Path | None = None,
                     source_sha: str | None = None, directory: str = "cargo") -> tuple[list[Dependency], list[Failure], set[str]]:
    """Enumerate Cargo dependencies, returning Cargo.lock's full expected key set."""

    lock = parse_cargo_lock(
        _require_regular_file(capture / directory / "Cargo.lock", CAPTURE_INCOMPLETE).read_text(
            encoding="utf-8"
        )
    )
    metadata = load_json(capture / directory / "metadata.json")
    graph = resolve_cargo_graph(metadata)
    root_package = next(
        package
        for package in metadata["packages"]
        if package["id"] == metadata["resolve"]["root"]
    )
    root_identity = _package_identity(root_package)
    workspace_value = metadata.get("workspace_root")
    workspace_root = PurePosixPath(workspace_value) if isinstance(workspace_value, str) else None
    if (workspace_root is None or not workspace_root.is_absolute()
            or ".." in workspace_root.parts):
        raise GateError(CAPTURE_INCOMPLETE, "cargo metadata workspace root is invalid")
    bound_root = None
    if source_root is not None:
        try:
            if not GIT_SHA_RE.fullmatch(source_sha or ""):
                raise ValueError("selected commit is not an exact SHA")
            bound_root = source_root.resolve(strict=True)
            if (subprocess.check_output(["git", "-C", str(bound_root), "rev-parse", "--show-toplevel"],
                                        text=True).strip() != str(bound_root)
                    or subprocess.check_output(["git", "-C", str(bound_root), "rev-parse", "HEAD"],
                                               text=True).strip() != source_sha):
                raise ValueError("source checkout differs from selected commit")
            if not workspace_root.is_relative_to(bound_root):
                raise ValueError("Cargo workspace is outside selected source")
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise GateError(CAPTURE_INCOMPLETE, "Cargo source checkout cannot be bound") from error

    def source_blob(path: Path) -> bytes:
        try:
            relative = path.relative_to(bound_root)
            if any((bound_root / parent).is_symlink() for parent in (relative, *relative.parents)):
                raise ValueError("source declaration is a symlink")
            blob = subprocess.check_output(["git", "-C", str(bound_root), "show", f"{source_sha}:{relative.as_posix()}"])
            if _require_regular_file(path, CAPTURE_INCOMPLETE).read_bytes() != blob:
                raise ValueError("source declaration differs from selected commit")
            return blob
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise GateError(CAPTURE_INCOMPLETE, "Cargo declaration cannot be bound to source") from error

    if bound_root is not None:
        committed_lock = source_blob(Path(workspace_root) / "Cargo.lock")
        if _require_regular_file(capture / directory / "Cargo.lock", CAPTURE_INCOMPLETE).read_bytes() != committed_lock:
            raise GateError(CAPTURE_INCOMPLETE, "captured Cargo lock differs from selected source")
    for package in [root_package, *graph.values()]:
        if package.get("source") is not None:
            continue
        manifest_value = package.get("manifest_path")
        manifest_path = PurePosixPath(manifest_value) if isinstance(manifest_value, str) else None
        if (manifest_path is None or not manifest_path.is_absolute()
                or ".." in manifest_path.parts
                or not manifest_path.is_relative_to(bound_root or workspace_root)):
            raise GateError(
                CAPTURE_INCOMPLETE,
                "source-bound Cargo package manifest is outside the release workspace",
            )
        if bound_root is not None:
            declaration = tomllib.loads(source_blob(Path(manifest_path)).decode("utf-8")).get("package", {})
            version = declaration.get("version")
            if version == {"workspace": True}:
                version = tomllib.loads(source_blob(Path(workspace_root) / "Cargo.toml").decode("utf-8"))["workspace"]["package"]["version"]
            if (declaration.get("name"), version) != _package_identity(package):
                raise GateError(CAPTURE_INCOMPLETE, "Cargo path identity differs from selected source")
    failures = reconcile_cargo(lock, graph, root_identity)
    external = {entry for entry, package in graph.items() if package.get("source") is not None}
    dependencies = [
        Dependency("cargo", name, version, frozenset({lock[(name, version)]}))
        for (name, version) in sorted(external & (set(lock) - {root_identity}))
        if lock[(name, version)] is not None
    ]
    # First-party path crates are bound by the source SHA. Every sourced lock
    # entry is gated, including build, dev, optional and cfg()-gated deps.
    expected = {
        f"cargo/{name}@{version}" for (name, version) in external & (set(lock) - {root_identity})
    }
    return dependencies, failures, expected


def _slug_for_key(key: str) -> str:
    """Return the capture filename stem for a canonical dependency key."""

    return key.replace("/", "__").replace("@", "__")


def _present_slugs(directory: Path) -> set[str]:
    """Return the stems of the regular ``.json`` files collected in a directory."""

    if directory.is_symlink() or not directory.is_dir():
        return set()
    return {
        entry.name[: -len(".json")]
        for entry in directory.iterdir()
        if entry.name.endswith(".json") and entry.is_file() and not entry.is_symlink()
    }


def validate_release_identity(repository: str, source_sha: str) -> None:
    """Require an ``owner/name`` repository and an exact 40-hex commit SHA.

    The reusable workflow can only declare these inputs as ``string``, so their
    shape is checked here. The gate calls it on the captured release, and the
    workflow calls it as its own first step so a malformed exact SHA is refused
    before any credentialed or model step runs.
    """

    if not REPOSITORY_RE.fullmatch(repository):
        raise GateError(CAPTURE_INCOMPLETE, "source_repository must be owner/name")
    if not GIT_SHA_RE.fullmatch(source_sha):
        raise GateError(CAPTURE_INCOMPLETE, "source_sha must be an exact 40-hex commit SHA")


def require_strix_credentials(
    environ: Mapping[str, str], names: Sequence[str] = STRIX_CREDENTIAL_NAMES
) -> list[Failure]:
    """Refuse the Strix stage when any provider credential is absent.

    The detail names only the absent variables. A credential that *is* present is
    never echoed, measured, or described, so no value or partial material can
    reach a log or a CI artifact through this path.
    """

    absent = [name for name in names if not str(environ.get(name, "")).strip()]
    if not absent:
        return []
    return [
        Failure(
            STRIX_CREDENTIALS_ABSENT,
            "strix",
            "the Strix stage requires provider credentials that are absent: "
            + ", ".join(sorted(absent)),
        )
    ]


def _scope_rows(
    capture: Path,
    ecosystems: Sequence[str],
    expected: Mapping[str, set[str]],
    dependencies: Sequence[Dependency],
) -> tuple[list[dict[str, Any]], list[Failure]]:
    """Compare each declared ecosystem's collected set against its expected set.

    CO#1226 accepted coverage because one component of one ecosystem existed. A
    full-set comparison is therefore required here: every expected member must be
    counted, enumerated, and matched by collected evidence *and* a fixture, and an
    ecosystem whose membership cannot be established fails rather than passes.
    """

    rows: list[dict[str, Any]] = []
    failures: list[Failure] = []
    evidence_slugs = _present_slugs(capture / "evidence")
    fixture_slugs = _present_slugs(capture / "strix" / "fixtures")
    every_expected_slug: set[str] = set()
    for ecosystem in ecosystems:
        subject = f"ecosystem/{ecosystem}"
        if ecosystem not in SUPPORTED_ECOSYSTEMS:
            failures.append(
                Failure(
                    SCOPE_UNVERIFIABLE,
                    subject,
                    "declared ecosystem has no enumerator, so its dependency scope "
                    "cannot be established",
                )
            )
            rows.append(
                {
                    "ecosystem": ecosystem,
                    "expected_count": 0,
                    "enumerated_count": 0,
                    "collected_count": 0,
                    "matched_count": 0,
                    "established": False,
                }
            )
            continue
        expected_keys = expected.get(ecosystem, set())
        expected_slugs = {_slug_for_key(key) for key in expected_keys}
        every_expected_slug |= expected_slugs
        prefix = SUPPORTED_ECOSYSTEMS[ecosystem]
        enumerated = {
            dependency.key for dependency in dependencies if dependency.ecosystem == prefix
        }
        collected = expected_slugs & evidence_slugs
        matched = collected & fixture_slugs
        row = {
            "ecosystem": ecosystem,
            "expected_count": len(expected_keys),
            "enumerated_count": len(enumerated),
            "collected_count": len(collected),
            "matched_count": len(matched),
            "established": True,
        }
        rows.append(row)
        if not expected_keys:
            failures.append(
                Failure(
                    SCOPE_UNVERIFIABLE,
                    subject,
                    "declared ecosystem resolved no expected dependency, so coverage "
                    "cannot be established",
                )
            )
            continue
        # Subset in any of the three directions refuses the release. Equality of
        # all four counts is the only accepted outcome.
        if not (len(expected_keys) == len(enumerated) == len(collected) == len(matched)):
            failures.append(
                Failure(
                    SCOPE_SET_MISMATCH,
                    subject,
                    f"expected {len(expected_keys)} dependencies but enumerated "
                    f"{len(enumerated)}, collected {len(collected)} evidence files and "
                    f"matched {len(matched)} fixtures",
                )
            )
        for slug in sorted(expected_slugs - evidence_slugs):
            failures.append(
                Failure(SCOPE_SET_MISMATCH, subject, f"no collected evidence for {slug}")
            )
        for slug in sorted(expected_slugs - fixture_slugs):
            failures.append(
                Failure(SCOPE_SET_MISMATCH, subject, f"no isolated fixture for {slug}")
            )
    # The reverse direction: capture material for something the producer never
    # declared is an unestablished scope, not a bonus.
    for slug in sorted((evidence_slugs | fixture_slugs) - every_expected_slug):
        failures.append(
            Failure(
                SCOPE_SET_MISMATCH,
                "capture",
                f"collected {slug} is absent from every declared ecosystem's expected set",
            )
        )
    return rows, failures


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
        "license_member_sha256": dict(evidence.get("license_member_sha256", {})),
        "license_selection_rationale": decision.rationale,
        "distribution_inclusion": inclusion,
        "native_properties": properties,
        "fixture_sha256": digest,
    }


_REVIEWED_SOURCE_NOTICES = {
    "cargo/profiling@1.0.18": (
        "3d595e54a326bc53c1c197b32d295e14b169e3cfeaa8dc82b529f947fba6bcf5",
        "aclysma/profiling", "8271551172eb6fa4cba47369aedd93790c623df9",
        "b2334c2698e538a45b779ef6da699a5a2a3a3f15578449ca8c3b3e87597bcd7b", {"MIT", "Apache-2.0"},
        (("LICENSE-MIT", 1093, "c8167fdeeed46d3f244d3f85c5bf998ce889343691c32be2c61a8bc4b5c08333"),
         ("LICENSE-APACHE", 10818, "10d30a673cd5e9349bdc02aeb48f14b3386d27d0da32df8f0a555d4aa16aa551"))),
    "cargo/jni-sys-macros@0.4.1": (
        "38c0b942f458fe50cdac086d2f946512305e5631e720728f2a61aabcd47a6264",
        "jni-rs/jni-sys", "64d77b7a5f119d7b55b4e2c169a4668067ff59e6",
        "d94eb8f006bda6a622d61a8b26fa0b763c7fc3479b40a24e32ef928e596e280c", {"MIT", "Apache-2.0"},
        (("LICENSE-MIT", 1071, "1d85bd754b04ceec93e98e890edd1fa3c6a22e81bcb32135806beeccefa51cd1"),
         ("LICENSE-APACHE", 11358, "c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08"))),
    "cargo/gl_generator@0.14.0": (
        "1a95dfc23a2b4a9a2f5ab41d194f8bfda3cabec42af4e39f08c339eb2a0c124d",
        "brendanzab/gl-rs", "ea503e8d5fb6d73c6030e6191ce738cd3bf3433e",
        "305ae3699231206e6368f716edf58b71162813708f7e5f7316ecb7b821ffcf31", {"Apache-2.0"},
        (("LICENSE", 11358, "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),)),
    "cargo/spirv@0.4.0+sdk-1.4.341.0": (
        "d9571ea910ebd84c86af4b3ed27f9dbdc6ad06f17c5f96146b2b671e2976744f",
        "gfx-rs/rspirv", "8afc3d0ac8e158128cd1410bb2e4b4c26ab11bb4",
        "fb183918865585d4d2443f1425d54374b6746b6c66f5c103a25ef0d569b8c90e", {"Apache-2.0 AND MIT-Khronos-old"},
        (("LICENSE", 11358, "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
         ("https://raw.githubusercontent.com/KhronosGroup/SPIRV-Headers/04f10f650d514df88b76d25e83db360142c7b174/LICENSE", 23503,
          "ea43b1de38a6f90c488800d66dec1ed671e68cda530266bc96951fb5b6307613"))),
}


def _source_license_notice(source: Path | None, source_sha: str, subject: str,
                           evidence: Mapping[str, Any], selection: Mapping[str, str] | None
                           ) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Authenticate separately retained grants for exact reviewed source archives.

    Complete upstream grants and byte-for-byte source correspondence are recorded
    in tests/fixtures/release_license_texts/provenance.json. These are source
    notice bytes, never claimed to be original crate members.
    """
    reviewed = _REVIEWED_SOURCE_NOTICES.get(subject)
    if (source is None or reviewed is None or selection is None
            or evidence.get("ecosystem") != "cargo"
            or evidence.get("source_sha256") != reviewed[0]):
        return {}, None
    _, repository, upstream_commit, digest, allowed_choices, grants = reviewed
    if not GIT_SHA_RE.fullmatch(source_sha):
        raise GateError(CAPTURE_INCOMPLETE, "source notice needs an exact release commit")

    def blob(path: str) -> bytes:
        entry = subprocess.check_output(
            ["git", "-C", str(source), "ls-tree", source_sha, "--", path], text=True)
        if not entry.startswith("100644 blob "):
            raise GateError(CAPTURE_INCOMPLETE, "source notice declaration/member is not a regular Git blob")
        oid = entry.split()[2]
        size = int(subprocess.check_output(["git", "-C", str(source), "cat-file", "-s", oid]))
        if size > _MAX_METADATA_BYTES:
            raise GateError(CAPTURE_INCOMPLETE, "source notice blob exceeds bounded size")
        return subprocess.check_output(["git", "-C", str(source), "cat-file", "blob", oid])

    choices = json.loads(blob("docs/release-license-selections.json"))
    if not isinstance(choices, list):
        raise GateError(CAPTURE_INCOMPLETE, "source notice selections must be a JSON array")
    name, version = subject.removeprefix("cargo/").split("@")
    matches = [row for row in choices if isinstance(row, Mapping)
               and (row.get("ecosystem"), row.get("name"), row.get("version")) == ("cargo", name, version)]
    if len(matches) != 1:
        raise GateError(LICENSE_TEXT_MISSING, f"source lacks one explicit notice selection: {subject}")
    choice = matches[0]
    upstream = [{"url": (name if name.startswith("https://") else
                         f"https://raw.githubusercontent.com/{repository}/{upstream_commit}/{name}"),
                 "sha256": sha} for name, _, sha in grants]
    notice = choice.get("bundled_notice", {})
    path = notice.get("path") if isinstance(notice, Mapping) else None
    if (any(choice.get(key) != selection.get(key) for key in ("chosen", "rationale"))
            or choice.get("chosen") not in allowed_choices
            or choice.get("archive_sha256") != evidence["source_sha256"]
            or choice.get("upstream_licenses") != upstream
            or not isinstance(path, str)
            or not re.fullmatch(r"python/fast_mlsirm/_licenses/[A-Za-z0-9_.+-]+[.]txt", path)
            or notice.get("sha256") != digest):
        raise GateError(SOURCE_HASH_MISMATCH, "reviewed supplemental notice declaration differs from reviewed source")
    content = blob(path)
    # The complete notice hash also binds any reviewed attribution suffix.
    if hashlib.sha256(content).hexdigest() != digest:
        raise GateError(SOURCE_HASH_MISMATCH, "reviewed source notice differs from complete upstream grants and notices")
    parts = []
    offset = 0
    for index, (_, size, sha) in enumerate(grants):
        if index:
            if content[offset:offset + 2] != b"\n\n":
                raise GateError(SOURCE_HASH_MISMATCH, "reviewed source grant separator differs")
            offset += 2
        part = content[offset:offset + size]
        if hashlib.sha256(part).hexdigest() != sha:
            raise GateError(SOURCE_HASH_MISMATCH, "reviewed source grant bytes differ from immutable upstream")
        parts.append(part)
        offset += size
    texts = {row["url"]: part.decode("utf-8") for row, part in zip(upstream, parts)}
    if subject == "cargo/spirv@0.4.0+sdk-1.4.341.0":
        # This exact multi-scope file grants all JSONs in its first section.
        # Later sections are explicitly scoped to XML, JsonCpp and docs, none of
        # which enter spirv's generator. The complete file remains in the notice
        # and upstream proof; only its byte-bound applicable grant is evaluated.
        texts[upstream[1]["url"]] = parts[1][:1361].decode("utf-8")
    return (texts,
            {"source_sha": source_sha, "path": path, "sha256": digest,
             "archive_sha256": evidence["source_sha256"], "upstream_commit": upstream_commit,
             "upstream_licenses": upstream})


def gate(capture_root: Path, stage: str = FULL_STAGE, *,
         source_root: Path | None = None) -> GateReport:
    """Run one fail-closed gate stage over a captured release.

    ``stage="license"`` establishes the full dependency scope and applies licence,
    evidence and deterministic-detector policy without reading any Strix binding,
    so it runs with no provider credential present. ``stage="full"`` additionally
    requires each dependency's machine-readable binding.
    """

    if stage not in GATE_STAGES:
        raise GateError(CAPTURE_INCOMPLETE, f"unknown gate stage: {stage!r}")
    capture = Path(capture_root)
    release = load_json(capture / "release.json")
    if not isinstance(release, Mapping):
        raise GateError(CAPTURE_INCOMPLETE, "release.json must be a JSON object")
    repository = str(release.get("source_repository", ""))
    source_sha = str(release.get("source_sha", ""))
    validate_release_identity(repository, source_sha)
    ecosystems = release.get("ecosystems")
    if not isinstance(ecosystems, list) or not ecosystems:
        raise GateError(CAPTURE_INCOMPLETE, "release.ecosystems must be a non-empty array")

    declared = [str(item) for item in ecosystems]
    report = GateReport(
        source_repository=repository, source_sha=source_sha, stage=stage
    )
    dependencies: list[Dependency] = []
    expected: dict[str, set[str]] = {}
    python_lock = capture / "python" / "lock.txt"
    if python_lock.is_file() and not python_lock.is_symlink():
        report.lock_sha256 = _sha256_file(python_lock)
    if "python" in declared:
        found, failures, expected["python"] = _enumerate_python(capture)
        dependencies.extend(found)
        report.failures.extend(failures)
    if "cargo" in declared:
        found, failures, expected["cargo"] = _enumerate_cargo(capture, source_root=source_root, source_sha=source_sha)
        root_lock = None
        if source_root is not None and subprocess.check_output(
                ["git", "-C", str(source_root), "ls-tree", source_sha, "--", "Cargo.lock"]):
            root_lock = subprocess.check_output(["git", "-C", str(source_root), "show", f"{source_sha}:Cargo.lock"])
        if root_lock is not None and (capture / "cargo/Cargo.lock").read_bytes() != root_lock:
            if not (capture / "cargo-dev").is_dir() or (capture / "cargo-dev").is_symlink():
                raise GateError(CAPTURE_INCOMPLETE, "development Cargo graph is missing")
            if _require_regular_file(capture / "cargo-dev/Cargo.lock", CAPTURE_INCOMPLETE).read_bytes() != root_lock:
                raise GateError(CAPTURE_INCOMPLETE, "development Cargo lock differs from source root")
        if (capture / "cargo-dev").exists():
            dev, dev_failures, dev_expected = _enumerate_cargo(
                capture, source_root=source_root, source_sha=source_sha, directory="cargo-dev")
            merged = {dependency.key: dependency for dependency in found}
            for dependency in dev:
                if dependency.key in merged and merged[dependency.key].expected_hashes != dependency.expected_hashes:
                    raise GateError(CARGO_LOCK_GRAPH_MISMATCH, "Cargo graphs disagree on dependency checksum")
                merged[dependency.key] = dependency
            found = [merged[key] for key in sorted(merged)]
            failures.extend(dev_failures)
            expected["cargo"].update(dev_expected)
        dependencies.extend(found)
        report.failures.extend(failures)
    # Every declared ecosystem is compared as a whole set before any dependency is
    # judged, so an unsupported or empty ecosystem cannot be masked by another
    # ecosystem that did resolve.
    scope_rows, scope_failures = _scope_rows(capture, declared, expected, dependencies)
    report.scopes.extend(scope_rows)
    report.failures.extend(scope_failures)
    # An empty enumeration can no longer reach this point silently: every shape
    # that yields zero dependencies also yields a failure above. A declared
    # ecosystem with no enumerator is SCOPE_UNVERIFIABLE; one whose expected set is
    # empty is SCOPE_UNVERIFIABLE; and a non-empty expected set that resolved
    # nothing is LOCK_ENV_MISMATCH or CARGO_LOCK_GRAPH_MISMATCH plus
    # SCOPE_SET_MISMATCH. A separate "enumerated nothing" guard here would be dead
    # code, so the invariant is asserted by
    # test_zero_enumerated_dependencies_always_carries_a_failure instead.

    selections = _load_selections(capture)
    if (capture / "license-selections.json").exists():
        report.license_selections_sha256 = _sha256_file(capture / "license-selections.json")
    if stage == FULL_STAGE:
        # Binder provenance belongs to the Strix stage only; a licence-stage report
        # must not claim it, or it would read as Strix evidence it never gathered.
        report.binder_sha256 = hashlib.sha256(
            resolve_evidence_binder().read_bytes()
        ).hexdigest()
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

        try:
            archive_path = capture / "archives" / f"{dependency.slug}.archive"
            if archive_path.parent.is_symlink():
                raise GateError(CAPTURE_INCOMPLETE, "archive directory is a symlink")
            bound = archive_license_evidence(read_archive_snapshot(archive_path), dependency.ecosystem)
            if any(evidence.get(key) != bound[key] for key in (
                    "source_sha256", "license_texts", "license_member_sha256")):
                report.failures.append(Failure(SOURCE_HASH_MISMATCH, subject,
                    "license evidence differs from the captured archive bytes"))
        except GateError as error:
            report.failures.append(Failure(error.code, subject, error.detail))
            continue

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
            or not set(inclusion).issubset({"wheel", "sdist", "crate", "dev"})
        ):
            raise GateError(
                EVIDENCE_INCOMPLETE,
                f"{subject}: distribution_inclusion must name wheel/sdist/crate/dev",
            )

        try:
            source_texts, source_notice = _source_license_notice(
                source_root, source_sha, subject, evidence, selections.get(subject))
        except GateError as error:
            report.failures.append(Failure(error.code, subject, error.detail))
            continue
        license_evidence = {**evidence, "license_texts": {**evidence["license_texts"], **source_texts}}
        license_failures, decision, license_source = evaluate_dependency_license(
            license_evidence, subject, selections.get(subject)
        )
        if source_notice is not None:
            license_source += " + exact immutable upstream grants retained in release source notice"
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
        if stage == FULL_STAGE:
            report.failures.extend(
                validate_strix_binding(
                    capture / "strix" / "bindings" / f"{dependency.slug}.json",
                    dependency,
                    evidence,
                    digest,
                    source_sha,
                )
            )
        row = _dependency_row(dependency, evidence, decision, license_source,
                              sorted(inclusion), properties, digest)
        if source_notice is not None:
            row["source_license_notice"] = source_notice
        report.dependencies.append(row)
    return report



def _strix_matrix_outputs(planned: list[dict[str, Any]]) -> dict[str, str]:
    """Partition the full plan while bounding GitHub's combined UTF-16 job output."""
    outputs = {
        "matrix_json": json.dumps({"include": planned[:STRIX_MATRIX_LIMIT]}, separators=(",", ":")),
        "matrix_overflow_json": json.dumps({"include": planned[STRIX_MATRIX_LIMIT:]}, separators=(",", ":")),
        "has_overflow": "true" if len(planned) > STRIX_MATRIX_LIMIT else "false",
    }
    if sum(len((key + value).encode("utf-16-le")) for key, value in outputs.items()) > 2 * STRIX_MATRIX_OUTPUT_MAX_BYTES:
        raise GateError(SCOPE_UNVERIFIABLE, "dependency matrix exceeds the bounded job output")
    return outputs


def strix_fanout_plan(
    capture_root: Path,
    license_report: Path,
    control_sha: str,
    run_id: int,
    run_attempt: int,
    archive_report: Path | None = None,
) -> dict[str, Any]:
    """Bind one bounded scan matrix to the passing licence stage's full set."""

    capture = Path(capture_root)
    report = load_json(license_report, LICENSE_MISSING)
    release = load_json(capture / "release.json")
    if not isinstance(report, Mapping) or not isinstance(release, Mapping):
        raise GateError(CAPTURE_INCOMPLETE, "fanout needs release and licence objects")
    repository = str(release.get("source_repository", ""))
    source_sha = str(release.get("source_sha", ""))
    validate_release_identity(repository, source_sha)
    if (report.get("result") != "PASS" or report.get("stage") != LICENSE_STAGE
            or report.get("source_repository") != repository
            or report.get("source_sha") != source_sha):
        raise GateError(LICENSE_MISSING, "fanout requires a passing matching licence report")
    if (not GIT_SHA_RE.fullmatch(control_sha) or type(run_id) is not int or run_id <= 0
            or type(run_attempt) is not int or run_attempt <= 0):
        raise GateError(CAPTURE_INCOMPLETE, "fanout execution identity is invalid")
    rows = report.get("dependencies")
    if not isinstance(rows, list) or not 1 <= len(rows) <= STRIX_PLAN_LIMIT:
        raise GateError(SCOPE_UNVERIFIABLE, "dependency plan is empty or exceeds 512 jobs")
    fixtures = capture / "strix" / "fixtures"
    if fixtures.is_symlink() or not fixtures.is_dir():
        raise GateError(CAPTURE_INCOMPLETE, "fixture directory is unavailable")
    planned: list[dict[str, Any]] = []
    base_members: set[str] = set()
    keys: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise GateError(CAPTURE_INCOMPLETE, "licence dependency row is malformed")
        key = row.get("key")
        expected_digest = row.get("fixture_sha256")
        if (not isinstance(key, str) or not key or key in keys
                or not isinstance(expected_digest, str)
                or not SHA256_RE.fullmatch(expected_digest)):
            raise GateError(CAPTURE_INCOMPLETE, "licence dependency key or fixture digest is invalid")
        slug = _slug_for_key(key)
        if (slug in {"", ".", ".."} or Path(slug).name != slug
                or "/" in slug or "\\" in slug):
            raise GateError(CAPTURE_INCOMPLETE, "dependency fixture slug is unsafe")
        fixture_path = _require_regular_file(fixtures / f"{slug}.json", CAPTURE_INCOMPLETE)
        digest_path = _require_regular_file(fixtures / f"{slug}.sha256", CAPTURE_INCOMPLETE)
        fixture = load_json(fixture_path)
        if (fixture_digest(fixture) != expected_digest
                or digest_path.read_text(encoding="utf-8").strip() != expected_digest):
            raise GateError(SOURCE_HASH_MISMATCH, f"{key}: fixture differs from the licence report")
        artifact_name = f"release-strix-binding-a{run_attempt}-" + hashlib.sha256(
            key.encode("utf-8")
        ).hexdigest()
        planned.append({"key": key, "slug": slug, "fixture_sha256": expected_digest,
                        "artifact_name": artifact_name, "fixture": fixture})
        base_members.update({f"{slug}.json", f"{slug}.sha256"})
        keys.add(key)
    if archive_report is not None:
        archive_payload = load_json(archive_report)
        archive_rows = archive_payload.get("archives") if isinstance(archive_payload, Mapping) else None
        build_rows = archive_payload.get("build_packages") if isinstance(archive_payload, Mapping) else None
        tool_rows = archive_payload.get("build_tools") if isinstance(archive_payload, Mapping) else None
        if (not isinstance(archive_payload, Mapping)
                or archive_payload.get("schema") != "cwl.release-runtime-archive-licenses/3"
                or not isinstance(archive_rows, list) or not archive_rows
                or not isinstance(build_rows, list) or not build_rows
                or not isinstance(tool_rows, list) or not tool_rows):
            raise GateError(SCOPE_UNVERIFIABLE, "runtime archive licence report is incomplete")
        for row, origin in [(item, "runtime_archive") for item in archive_rows] + [
            (item, "build_package") for item in build_rows
        ] + [
            (item, "build_tool") for item in tool_rows
        ]:
            if not isinstance(row, Mapping):
                raise GateError(CAPTURE_INCOMPLETE, "runtime archive licence row is malformed")
            key, name, version = row.get("key"), row.get("name"), row.get("version")
            source_hash, fixture, digest = row.get("source_sha256"), row.get("fixture"), row.get("fixture_sha256")
            ecosystem = "github-release" if origin == "build_tool" else "pypi"
            if (not all(isinstance(value, str) and value for value in (key, name, version, source_hash, digest))
                    or not SHA256_RE.fullmatch(source_hash) or not SHA256_RE.fullmatch(digest)
                    or key != f"{ecosystem}/{name}@{version}/sha256/{source_hash}"
                    or row.get("package_key") != f"{ecosystem}/{name}@{version}"
                    or key in keys or not isinstance(fixture, Mapping)
                    or fixture.get("id") != key
                    or fixture.get("dependency") != {"ecosystem": ecosystem, "name": name,
                                                     "version": version, "source_sha256": source_hash}
                    or fixture_digest(fixture) != digest
                    or not isinstance(row.get("license"), str) or not row["license"]):
                raise GateError(SOURCE_HASH_MISMATCH, "runtime archive fixture differs from licence verdict")
            slug = _slug_for_key(key)
            planned.append({"key": key, "slug": slug, "fixture_sha256": digest,
                            "artifact_name": f"release-strix-binding-a{run_attempt}-"
                            + hashlib.sha256(key.encode("utf-8")).hexdigest(),
                            "fixture": fixture,
                            origin: {"package_key": row["package_key"],
                                     "source_sha256": source_hash}})
            keys.add(key)
    if len(planned) > STRIX_PLAN_LIMIT:
        raise GateError(SCOPE_UNVERIFIABLE, "dependency plan exceeds 512 jobs")
    if (len({item["slug"] for item in planned}) != len(planned)
            or {entry.name for entry in fixtures.iterdir()} != base_members
            or any(entry.is_symlink() or not entry.is_file() for entry in fixtures.iterdir())):
        raise GateError(SCOPE_SET_MISMATCH, "fixture directory differs from the exact licence set")
    _strix_matrix_outputs(planned)
    result = {
        "schema": "cwl.release-strix-fanout-plan/1",
        "source_repository": repository,
        "source_sha": source_sha,
        "control_sha": control_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "license_report_sha256": _sha256_file(license_report),
        "dependencies": planned,
    }
    if archive_report is not None:
        result["runtime_archive_license_sha256"] = _sha256_file(archive_report)
    return result


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
    # A passing licence-stage report proves nothing about Strix. Only the full
    # stage may be sealed, so a prescreen can never stand in for the Strix stage.
    if report.get("stage") != FULL_STAGE:
        raise GateError(
            CAPTURE_INCOMPLETE,
            "refusing to seal evidence for a gate report that is not the full stage",
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


def distribution_declared_metadata(
    distribution: Path, name: str, version: str
) -> dict[str, Any]:
    """Return one fetched distribution's own declared identity and licence fields.

    The licence determination has to happen *before* the release closure is
    installed, so it reads the distribution's own ``METADATA``/``PKG-INFO``
    rather than ``pip inspect`` of an environment that only exists after an
    install. The pin is re-checked against what the archive declares, so a file
    whose metadata names another project or version fails here instead of being
    adjudicated under the wrong identity.
    """

    _require_regular_file(distribution, CAPTURE_INCOMPLETE)
    text = _declared_metadata_text(distribution)
    # ``METADATA`` is an RFC 822 header block; ``Classifier`` repeats.
    message = email.parser.Parser().parsestr(text)
    declared_name = str(message.get("Name", ""))
    declared_version = str(message.get("Version", ""))
    if normalize_project_name(declared_name) != normalize_project_name(name):
        raise GateError(
            CAPTURE_INCOMPLETE,
            f"{distribution.name}: declares project {declared_name!r}, pinned as {name!r}",
        )
    if declared_version.strip() != version:
        raise GateError(
            CAPTURE_INCOMPLETE,
            f"{distribution.name}: declares version {declared_version!r}, pinned as {version!r}",
        )
    classifiers = [
        value
        for value in message.get_all("Classifier", [])
        if isinstance(value, str) and value.startswith("License ")
    ]
    return {
        "ecosystem": "pypi",
        "name": name,
        "version": version,
        "license_expression": str(message.get("License-Expression", "")),
        "license": str(message.get("License", "")),
        "classifiers": classifiers,
        "distribution_inclusion": ["sdist", "wheel"],
        "known_vulnerabilities": [],
    }


def _declared_metadata_text(distribution: Path) -> str:
    """Extract the metadata header block from a wheel or a source distribution."""

    if distribution.suffix == ".whl":
        with zipfile.ZipFile(distribution) as archive:
            members = [
                member
                for member in archive.namelist()
                if PurePosixPath(member).match("*.dist-info/METADATA")
                and len(PurePosixPath(member).parts) == 2
            ]
            if len(members) != 1:
                raise GateError(
                    CAPTURE_INCOMPLETE,
                    f"{distribution.name}: expected exactly one dist-info/METADATA, "
                    f"found {len(members)}",
                )
            return _bounded_archive_text(archive.getinfo(members[0]), archive)
    with tarfile.open(distribution) as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and len(PurePosixPath(member.name).parts) == 2
            and PurePosixPath(member.name).name == "PKG-INFO"
        ]
        if len(members) != 1:
            raise GateError(
                CAPTURE_INCOMPLETE,
                f"{distribution.name}: expected exactly one top-level PKG-INFO, "
                f"found {len(members)}",
            )
        if members[0].size > _MAX_METADATA_BYTES:
            raise GateError(
                CAPTURE_INCOMPLETE, f"{distribution.name}: metadata exceeds the bounded read"
            )
        handle = archive.extractfile(members[0])
        if handle is None:  # pragma: no cover - defensive; isfile() was checked
            raise GateError(CAPTURE_INCOMPLETE, f"{distribution.name}: PKG-INFO is unreadable")
        with handle:
            return _decode_metadata(handle.read(_MAX_METADATA_BYTES + 1), distribution)


def _bounded_archive_text(info: zipfile.ZipInfo, archive: zipfile.ZipFile) -> str:
    """Read one zip member as text, refusing anything past the bounded size."""

    if info.file_size > _MAX_METADATA_BYTES:
        raise GateError(CAPTURE_INCOMPLETE, f"{info.filename}: metadata exceeds the bounded read")
    with archive.open(info) as handle:
        return _decode_metadata(handle.read(_MAX_METADATA_BYTES + 1), Path(info.filename))


def _decode_metadata(raw: bytes, origin: Path) -> str:
    """Decode a bounded metadata block, refusing oversize or non-UTF-8 content."""

    if len(raw) > _MAX_METADATA_BYTES:
        raise GateError(CAPTURE_INCOMPLETE, f"{origin.name}: metadata exceeds the bounded read")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GateError(CAPTURE_INCOMPLETE, f"{origin.name}: metadata is not UTF-8") from error


def bind_install_requirements(
    report: Path, capture: Path, download_root: Path, output: Path
) -> list[str]:
    """Narrow the install to exactly the artifacts this verdict judged.

    A passing report is not by itself permission to install: without a binding,
    the install re-reads the original lock, and a lock that records several hashes
    for one project accepts an artifact whose licence and contents were never
    judged. This refuses unless the lock still digests to what the verdict read,
    every judged artifact is present in the collected root by digest, and the root
    holds no other distribution; it then writes a requirements file pinning each
    project to the one judged digest, so ``--require-hashes`` can only install the
    inspected bytes.
    """

    install_is_authorized(report)
    payload = load_json(_require_regular_file(report, LICENSE_MISSING), LICENSE_MISSING)
    lock = capture / "python" / "lock.txt"
    recorded_lock = str(payload.get("python_lock_sha256") or "")
    if not SHA256_RE.fullmatch(recorded_lock):
        raise GateError(
            LICENSE_MISSING, "the report records no python lock digest to bind against"
        )
    if _sha256_file(_require_regular_file(lock, SOURCE_HASH_MISMATCH)) != recorded_lock:
        raise GateError(
            SOURCE_HASH_MISMATCH,
            "the lock to install from is not the lock the licence stage judged",
        )
    judged: dict[str, tuple[str, str]] = {}
    rows = payload.get("dependencies")
    if not isinstance(rows, list):
        raise GateError(LICENSE_MISSING, "the report records no dependency rows")
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("ecosystem")) != "pypi":
            continue
        digest = str(row.get("source_sha256") or "")
        if not SHA256_RE.fullmatch(digest):
            raise GateError(
                SOURCE_HASH_MISMATCH,
                f"judged dependency {row.get('key')!r} carries no usable source digest",
            )
        judged[digest] = (str(row.get("name") or ""), str(row.get("version") or ""))
    if not judged:
        raise GateError(LICENSE_MISSING, "the report judged no Python distribution")
    collected: dict[str, Path] = {}
    collected_evidence: dict[str, dict[str, Any]] = {}
    for candidate in sorted(Path(download_root).iterdir()):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.suffix not in {".whl", ".zip", ".gz", ".bz2", ".xz", ".tgz"}:
            continue
        bound = archive_license_evidence(read_archive_snapshot(candidate), "pypi")
        collected[bound["source_sha256"]] = candidate
        collected_evidence[bound["source_sha256"]] = bound
    missing = sorted(digest for digest in judged if digest not in collected)
    if missing:
        raise GateError(
            SOURCE_HASH_MISMATCH,
            "the collected root is missing judged artifacts: " + ", ".join(missing),
        )
    unjudged = sorted(
        collected[digest].name for digest in collected if digest not in judged
    )
    if unjudged:
        raise GateError(
            SOURCE_HASH_MISMATCH,
            "the collected root holds unjudged distributions: " + ", ".join(unjudged),
        )
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("ecosystem")) != "pypi":
            continue
        bound = collected_evidence[str(row["source_sha256"])]
        if row.get("license_member_sha256") != bound["license_member_sha256"]:
            raise GateError(SOURCE_HASH_MISMATCH, "report license-member hashes differ from install archive")
        failures, _, _ = evaluate_dependency_license(
            {"license_expression": row.get("license"), "license_texts": bound["license_texts"]},
            str(row.get("key", "")), None)
        if failures:
            raise GateError(failures[0].code, "install archive license text does not pass the recorded selection")
    lines = [
        f"{name}=={version} --hash=sha256:{digest}"
        for digest, (name, version) in sorted(judged.items(), key=lambda item: item[1])
    ]
    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def install_is_authorized(report: Path) -> None:
    """Raise unless a prescreen report authorizes installing the release closure.

    The install of the release closure is the first action that runs dependency
    code, so it may only happen after the licence stage has passed. The report
    is the recorded evidence of that pass; a missing, malformed, or failing
    report refuses the install rather than defaulting to permitted.
    """

    payload = load_json(_require_regular_file(report, LICENSE_MISSING), LICENSE_MISSING)
    if not isinstance(payload, Mapping):
        raise GateError(LICENSE_MISSING, "prescreen report must be a JSON object")
    if payload.get("stage") != LICENSE_STAGE:
        raise GateError(
            LICENSE_MISSING,
        LICENSE_SELECTION_INVALID,
            f"prescreen report records stage {payload.get('stage')!r}, not {LICENSE_STAGE!r}",
        )
    if payload.get("result") != "PASS":
        raise GateError(
            LICENSE_MISSING,
        LICENSE_SELECTION_INVALID,
            f"prescreen report records result {payload.get('result')!r}, not 'PASS'",
        )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: ``validate-inputs`` and ``prescreen`` refuse a release before any
    credential exists, ``require-strix-credentials`` refuses a credential-less Strix
    stage, ``install-authorized`` refuses an install the licence stage did not clear,
    ``gate`` refuses a release, and ``seal`` composes the attestation.
    """

    parser = argparse.ArgumentParser(description="Pre-publish dependency gate")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("capture", help="Assemble evidence and fixtures from raw output")
    collect.add_argument("--raw", required=True)
    collect.add_argument("--capture", required=True)

    identity = sub.add_parser(
        "validate-inputs", help="Refuse a malformed repository or exact release SHA"
    )
    identity.add_argument("--source-repository", required=True)
    identity.add_argument("--source-sha", required=True)

    sources = sub.add_parser(
        "lock-source-options",
        help="Emit validated pip source options so download resolves like install",
    )
    sources.add_argument("--lock", required=True)
    sources.add_argument("--permitted-root", required=True)

    screen = sub.add_parser(
        "prescreen", help="Refuse a denied or unverifiable licence before any credential"
    )
    screen.add_argument("--capture", required=True)
    screen.add_argument("--report", required=True)
    screen.add_argument("--source")

    fanout = sub.add_parser(
        "fanout-plan", help="Emit a bounded exact dependency matrix after licence approval"
    )
    fanout.add_argument("--capture", required=True)
    fanout.add_argument("--license-report", required=True)
    fanout.add_argument("--control-sha", required=True)
    fanout.add_argument("--run-id", required=True, type=int)
    fanout.add_argument("--run-attempt", required=True, type=int)
    fanout.add_argument("--runtime-archive-license-report")
    fanout.add_argument("--output", required=True)

    sub.add_parser(
        "require-strix-credentials", help="Refuse the Strix stage when a credential is absent"
    )

    declared = sub.add_parser(
        "distribution-metadata",
        help="Emit one fetched distribution's declared identity and licence fields",
    )
    declared.add_argument("--distribution", required=True)
    declared.add_argument("--name", required=True)
    declared.add_argument("--version", required=True)

    permit = sub.add_parser(
        "install-authorized",
        help="Refuse installing the release closure unless the licence stage passed",
    )
    permit.add_argument("--report", required=True)

    bind = sub.add_parser(
        "bind-install",
        help="Pin the install to exactly the artifacts and lock the verdict judged",
    )
    bind.add_argument("--report", required=True)
    bind.add_argument("--capture", required=True)
    bind.add_argument("--download-root", required=True)
    bind.add_argument("--output", required=True)

    selections = sub.add_parser("capture-license-selections")
    selections.add_argument("--source", required=True)
    selections.add_argument("--source-sha", required=True)
    selections.add_argument("--capture", required=True)

    run = sub.add_parser("gate", help="Refuse the release unless every check passes")
    run.add_argument("--capture", required=True)
    run.add_argument("--report", required=True)
    run.add_argument("--source")

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
        if args.command == "capture-license-selections":
            capture_license_selections(Path(args.source), args.source_sha, Path(args.capture))
            return 0
        if args.command == "capture":
            keys = capture(Path(args.raw), Path(args.capture))
            json.dump({"captured": keys}, sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        if args.command == "validate-inputs":
            validate_release_identity(args.source_repository, args.source_sha)
            print("Release identity inputs are well formed.")
            return 0
        if args.command == "lock-source-options":
            # One option per line: the caller reads them into a bash array, so no
            # value is ever word-split or re-interpreted by a shell.
            for option in lock_download_options(
                _require_regular_file(Path(args.lock), LOCK_SOURCE_UNSUPPORTED).read_text(
                    encoding="utf-8"
                ),
                Path(args.permitted_root),
            ):
                print(option)
            return 0
        if args.command == "distribution-metadata":
            json.dump(
                distribution_declared_metadata(
                    Path(args.distribution), args.name, args.version
                ),
                sys.stdout,
                indent=2,
                sort_keys=True,
            )
            sys.stdout.write("\n")
            return 0
        if args.command == "bind-install":
            for line in bind_install_requirements(
                Path(args.report),
                Path(args.capture),
                Path(args.download_root),
                Path(args.output),
            ):
                print(line)
            return 0
        if args.command == "install-authorized":
            install_is_authorized(Path(args.report))
            print("Licence stage passed; installing the prescreened closure is authorized.")
            return 0
        if args.command == "require-strix-credentials":
            failures = require_strix_credentials(os.environ)
            for failure in failures:
                print(f"ERROR: {failure.code}: {failure.detail}", file=sys.stderr)
            return 2 if failures else 0
        if args.command == "fanout-plan":
            plan = strix_fanout_plan(
                Path(args.capture), Path(args.license_report), args.control_sha,
                args.run_id, args.run_attempt,
                Path(args.runtime_archive_license_report) if args.runtime_archive_license_report else None,
            )
            path = Path(args.output)
            if path.exists() or path.is_symlink():
                raise GateError(CAPTURE_INCOMPLETE, "fanout plan output already exists")
            path.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
            write_github_output(_strix_matrix_outputs(plan["dependencies"]), destination)
            print(json.dumps(plan, sort_keys=True))
            return 0
        if args.command in {"gate", "prescreen"}:
            stage = FULL_STAGE if args.command == "gate" else LICENSE_STAGE
            report = gate(Path(args.capture), stage=stage,
                          source_root=Path(args.source) if args.source else None)
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
