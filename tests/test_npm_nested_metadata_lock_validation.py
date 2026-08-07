"""Contracts for npm v2/v3 metadata-only nested package locations."""

from __future__ import annotations

import json

import pytest

from scripts.ci import materialize_base_javascript_packages as materializer


_VALID_INTEGRITY = "sha512-" + ("A" * 86) + "=="


def _pinned(version: str, package_name: str) -> dict[str, str]:
    """Return one exact public-registry package pin."""

    archive_name = package_name.rsplit("/", 1)[-1]
    return {
        "version": version,
        "resolved": (
            f"https://registry.npmjs.org/{package_name}/-/"
            f"{archive_name}-{version}.tgz"
        ),
        "integrity": _VALID_INTEGRITY,
    }


def _lock(packages: dict[str, object]) -> bytes:
    """Serialize one npm lock fixture as UTF-8 JSON bytes."""

    return json.dumps(
        {"lockfileVersion": 3, "packages": packages},
        sort_keys=True,
    ).encode("utf-8")


def test_accepts_bandscope_scoped_metadata_through_exact_root_pin() -> None:
    """A BandScope-shaped peer location may reuse one exact canonical pin."""

    packages = {
        "": {"name": "bandscope"},
        "node_modules/@types/react-dom": _pinned("19.1.7", "@types/react-dom"),
        "apps/desktop/node_modules/@types/react-dom": {
            "version": "19.1.7",
            "dev": True,
            "peer": True,
        },
    }

    materializer.validate_head_npm_lock("package-lock.json", _lock(packages))


def test_accepts_unscoped_metadata_and_independently_pinned_nested_version() -> None:
    """Metadata reuse and an independently complete nested pin can coexist."""

    packages = {
        "node_modules/react": _pinned("19.1.1", "react"),
        "apps/web/node_modules/react": {"version": "19.1.1", "peer": True},
        "node_modules/legacy/node_modules/react": _pinned("18.3.1", "react"),
    }

    materializer.validate_head_npm_lock("package-lock.json", _lock(packages))


@pytest.mark.parametrize(
    ("packages", "message"),
    [
        (
            {"apps/web/node_modules/react": {"version": "19.1.1"}},
            "canonical root pin",
        ),
        (
            {
                "node_modules/react": _pinned("19.1.1", "react"),
                "apps/web/node_modules/react": {"version": "19.1.0"},
            },
            "exact canonical version",
        ),
        (
            {
                "node_modules/react": {
                    "version": "19.1.1",
                    "resolved": _pinned("19.1.1", "react")["resolved"],
                },
                "apps/web/node_modules/react": {"version": "19.1.1"},
            },
            "registry tarball and SHA-512 integrity",
        ),
        (
            {
                "node_modules/react": _pinned("19.1.1", "react"),
                "apps/web/node_modules/react": {
                    "version": "19.1.1",
                    "resolved": _pinned("19.1.1", "react")["resolved"],
                },
            },
            "must not partially declare",
        ),
        (
            {
                "node_modules/react": _pinned("19.1.1", "react"),
                "apps/web/node_modules/react": {
                    "version": "19.1.1",
                    "integrity": _VALID_INTEGRITY,
                },
            },
            "must not partially declare",
        ),
        (
            {
                "node_modules/react": {
                    **_pinned("19.1.1", "react"),
                    "resolved": "https://example.invalid/react-19.1.1.tgz",
                },
                "apps/web/node_modules/react": {"version": "19.1.1"},
            },
            "must resolve from https://registry.npmjs.org/",
        ),
        (
            {
                "node_modules/react": {
                    **_pinned("19.1.1", "react"),
                    "integrity": "sha512-invalid",
                },
                "apps/web/node_modules/react": {"version": "19.1.1"},
            },
            "must use one SHA-512 integrity value",
        ),
        (
            {"apps/web/node_modules/@types": {"version": "1.0.0"}},
            "malformed npm package identity",
        ),
        (
            {"apps/web/node_modules/@types/react/extra": {"version": "1.0.0"}},
            "malformed npm package identity",
        ),
        (
            {
                "node_modules/react": {
                    "version": "19.1.1",
                    "dev": True,
                }
            },
            "canonical root pin",
        ),
        (
            {
                "node_modules/react": _pinned("19.1.1", "react"),
                "apps/web/node_modules/react": {"version": ""},
            },
            "nonempty exact version",
        ),
    ],
)
def test_rejects_untrusted_metadata_only_nested_locations(
    packages: dict[str, object],
    message: str,
) -> None:
    """Every metadata-only location must close through one exact safe root pin."""

    with pytest.raises(ValueError, match=message):
        materializer.validate_head_npm_lock("package-lock.json", _lock(packages))
