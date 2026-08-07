#!/usr/bin/env python3
"""Apply the reviewed PR 807 canonical npm metadata implementation once."""

from __future__ import annotations

from pathlib import Path


SOURCE_PATH = Path("scripts/ci/materialize_base_javascript_packages.py")
DOCTORING_PATH = Path("docs/doctoring/npm-nested-metadata-canonical-pins.md")
CHANGELOG_PATH = Path("CHANGELOG.md")


HELPERS = r'''

def _npm_package_identity(candidate: pathlib.PurePosixPath) -> str | None:
    """Return the exact package identity after the final node_modules segment."""

    positions = [
        index for index, segment in enumerate(candidate.parts) if segment == "node_modules"
    ]
    if not positions:
        return None
    tail = candidate.parts[positions[-1] + 1 :]
    if len(tail) == 1 and not tail[0].startswith("@"):
        identity = tail[0]
    elif len(tail) == 2 and tail[0].startswith("@"):
        identity = f"{tail[0]}/{tail[1]}"
    else:
        return None
    return identity if NPM_PACKAGE_IDENTITY_RE.fullmatch(identity) else None


def _validate_npm_registry_pin(
    lock_path: str,
    package_path: str,
    resolved: object,
    integrity: object,
) -> None:
    """Require one exact public npm tarball and SHA-512 integrity pair."""

    if not isinstance(resolved, str) or not isinstance(integrity, str):
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} must pin a registry tarball and SHA-512 integrity"
        )
    parsed = urllib.parse.urlsplit(resolved)
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} has an invalid registry URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != NPM_REGISTRY_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or not parsed.path.endswith(".tgz")
    ):
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} must resolve from https://{NPM_REGISTRY_HOST}/"
        )
    if not SHA512_SRI_RE.fullmatch(integrity):
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} must use one SHA-512 integrity value"
        )


def validate_head_npm_lock(lock_path: str, lock_content: bytes) -> None:
'''


NEW_LOOP = r'''    for package_path, metadata in sorted(packages.items()):
        if not isinstance(package_path, str) or not isinstance(metadata, dict):
            raise ValueError(
                f"current-head npm lock {lock_path} contains malformed package metadata"
            )
        if "\\" in package_path:
            raise ValueError(
                f"current-head npm lock {lock_path} contains unsafe package path {package_path!r}"
            )
        candidate = pathlib.PurePosixPath(package_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                f"current-head npm lock {lock_path} contains unsafe package path {package_path!r}"
            )
        if not package_path or "node_modules" not in candidate.parts:
            continue

        resolved = metadata.get("resolved")
        if metadata.get("link") is True:
            if not isinstance(resolved, str) or not resolved or "\\" in resolved:
                raise ValueError(
                    f"current-head npm lock {lock_path} contains an unsafe workspace link for {package_path}"
                )
            link_target = pathlib.PurePosixPath(resolved)
            if (
                link_target.is_absolute()
                or ".." in link_target.parts
                or "node_modules" in link_target.parts
            ):
                raise ValueError(
                    f"current-head npm lock {lock_path} contains an unsafe workspace link for {package_path}"
                )
            continue

        identity = _npm_package_identity(candidate)
        if identity is None:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} has a malformed npm package identity"
            )

        has_resolved = "resolved" in metadata
        has_integrity = "integrity" in metadata
        if has_resolved != has_integrity:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must not partially declare resolved or integrity"
            )
        if has_resolved:
            _validate_npm_registry_pin(
                lock_path,
                package_path,
                metadata.get("resolved"),
                metadata.get("integrity"),
            )
            continue

        version = metadata.get("version")
        if not isinstance(version, str) or not version:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must declare a nonempty exact version"
            )
        canonical_path = f"node_modules/{identity}"
        if package_path == canonical_path:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must provide a canonical root pin"
            )
        canonical_metadata = packages.get(canonical_path)
        if (
            not isinstance(canonical_metadata, dict)
            or canonical_metadata.get("link") is True
        ):
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} has no canonical root pin at {canonical_path}"
            )
        canonical_version = canonical_metadata.get("version")
        if not isinstance(canonical_version, str) or not canonical_version:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} has no canonical root pin at {canonical_path}"
            )
        if canonical_version != version:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must match the exact canonical version at {canonical_path}"
            )
        _validate_npm_registry_pin(
            lock_path,
            canonical_path,
            canonical_metadata.get("resolved"),
            canonical_metadata.get("integrity"),
        )
'''


DOCTORING = """# Canonical pins for metadata-only nested npm locations

## Decision

Changed-head npm lock validation continues to accept only lockfile versions 2 and
3, safe repository-relative package locations, safe workspace links, and exact
public-registry SHA-512 artifact pins. One narrowly defined npm serialization is
also accepted: a non-link nested `node_modules` location may omit `resolved` and
`integrity` only when it declares a nonempty exact `version` and the canonical
root location for the same normalized package identity supplies the same version,
one HTTPS `registry.npmjs.org` tarball, and one valid SHA-512 SRI value.

For `apps/desktop/node_modules/@types/react-dom`, the only eligible canonical
location is `node_modules/@types/react-dom`. Scoped identity is derived from the
two segments after the final `node_modules`; an unscoped identity uses exactly
one segment. Missing, malformed, linked, version-mismatched, partially pinned,
non-registry, or invalid-integrity canonical evidence fails closed. Complete
nested pins remain independently valid and are not rebound to another version.

## Trust and interpretation boundary

The validator consumes the original lock bytes unchanged. It does not repair,
resolve, install, fetch, infer a version range, or synthesize artifact metadata.
The canonical lookup is a structural provenance check for one lock document, not
a claim that arbitrary duplicated locations are interchangeable. Pull-request
code and lifecycle hooks remain outside the trusted materializer.

npm documents `packages` as a location-keyed map and notes that descriptors may
contain version and classification metadata while artifact fields depend on the
resolved dependency form. npm workspaces are managed from one top-level package
and lock while nested packages are linked into the root installation. This
central policy is intentionally stricter: a metadata-only installed location is
accepted only through one exact root package identity, version, registry origin,
and SHA-512 integrity closure.

## Verification

Permanent tests include the BandScope scoped peer shape, an unscoped equivalent,
an independently pinned nested version, missing canonical metadata, version
mismatch, partial pins, hostile registry URLs, invalid SRI, malformed scoped and
unscoped identities, empty versions, and metadata-only root entries. Python 3.10
compilation and Python 3.14 focused/full tests enforce complete production
statement, branch, and public-docstring coverage.

## Rollback

Rollback removes the canonical metadata-only branch and returns to rejecting all
non-link installed locations without local artifact fields. It must not weaken
URL, path, link, lock-version, SHA-512, immutable-source, or offline-execution
controls.

## References

npm, Inc. (2026). *package-lock.json*. npm Docs.
https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json/

npm, Inc. (2026). *Workspaces*. npm Docs.
https://docs.npmjs.com/cli/v11/using-npm/workspaces/
"""


def main() -> None:
    """Apply the bounded implementation, doctoring, and changelog edits."""

    source = SOURCE_PATH.read_text(encoding="utf-8")
    constant_anchor = 'SHA512_SRI_RE = re.compile(r"^sha512-[A-Za-z0-9+/]{86}==$")\n'
    constant_replacement = constant_anchor + (
        "NPM_PACKAGE_IDENTITY_RE = re.compile(\n"
        '    r"^(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$"\n'
        ")\n"
    )
    if source.count(constant_anchor) != 1:
        raise SystemExit("npm identity constant anchor changed")
    source = source.replace(constant_anchor, constant_replacement, 1)

    function_anchor = (
        "\ndef validate_head_npm_lock(lock_path: str, lock_content: bytes) -> None:\n"
    )
    if source.count(function_anchor) != 1:
        raise SystemExit("validator function anchor changed")
    source = source.replace(function_anchor, HELPERS, 1)

    loop_start = source.index(
        "    for package_path, metadata in sorted(packages.items()):\n"
    )
    loop_end = source.index("\n\ndef materialize(\n", loop_start)
    SOURCE_PATH.write_text(
        source[:loop_start] + NEW_LOOP + source[loop_end:],
        encoding="utf-8",
    )

    DOCTORING_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCTORING_PATH.write_text(DOCTORING, encoding="utf-8")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    fixed_anchor = "### Fixed\n\n"
    entry = (
        "- Accepted metadata-only nested npm v2/v3 package locations only when one "
        "canonical root package has the same normalized identity and exact version "
        "plus a validated public-registry tarball and SHA-512 integrity, while "
        "retaining fail-closed path, link, partial-pin, origin, and SRI controls.\n"
    )
    if changelog.count(fixed_anchor) != 1:
        raise SystemExit("CHANGELOG Fixed anchor changed")
    if entry not in changelog:
        changelog = changelog.replace(fixed_anchor, fixed_anchor + entry, 1)
    CHANGELOG_PATH.write_text(changelog, encoding="utf-8")


if __name__ == "__main__":
    main()
