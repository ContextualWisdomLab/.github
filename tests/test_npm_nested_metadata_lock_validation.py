"""Contracts for npm v2/v3 metadata-only nested package locations."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_regular_base_path_filter_covers_every_rejection_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tree parsing ignores trees, symlinks, absolute paths, and traversal paths."""

    def git_stub(_repo_root: Path, *args: str) -> bytes:
        assert args[:4] == ("ls-tree", "-r", "-z", "--full-tree")
        return b"".join(
            (
                b"040000 tree " + (b"0" * 40) + b"\tdirectory\0",
                b"120000 blob " + (b"1" * 40) + b"\tsymlink\0",
                b"100644 blob " + (b"2" * 40) + b"\t/absolute\0",
                b"100644 blob " + (b"3" * 40) + b"\t../escape\0",
                b"100644 blob " + (b"4" * 40) + b"\tpackage.json\0",
            )
        )

    monkeypatch.setattr(materializer, "_git", git_stub)
    assert materializer._regular_base_paths(tmp_path, "a" * 40) == {"package.json"}


@pytest.mark.parametrize(
    "lock_document",
    [
        {"lockfileVersion": 3},
        {
            "lockfileVersion": 3,
            "packages": {"packages/missing": {"version": "1.0.0"}},
        },
    ],
)
def test_base_npm_materialization_covers_optional_workspace_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lock_document: dict[str, object],
) -> None:
    """Missing packages maps and absent workspace manifests stay non-fatal."""

    monkeypatch.setattr(
        materializer,
        "_regular_base_paths",
        lambda _repo_root, _base_sha: {"package.json", "package-lock.json"},
    )

    def git_stub(_repo_root: Path, *args: str) -> bytes:
        assert args[0] == "show"
        target = args[1].split(":", 1)[1]
        if target == "package.json":
            return b'{"name":"fixture"}\n'
        if target == "package-lock.json":
            return json.dumps(lock_document).encode("utf-8")
        raise AssertionError(target)

    monkeypatch.setattr(materializer, "_git", git_stub)
    projects = materializer.base_npm_projects(tmp_path, "a" * 40)
    assert len(projects) == 1
    assert set(projects[0][2]) == {"package.json", "package-lock.json"}


def test_registry_pin_rejects_non_string_metadata() -> None:
    """Registry provenance fields must be exact strings before URL parsing."""

    with pytest.raises(ValueError, match="must pin a registry tarball"):
        materializer._validate_npm_registry_pin(
            "package-lock.json",
            "node_modules/react",
            123,
            _VALID_INTEGRITY,
        )


def test_materialize_rejects_symlinked_output_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parent symlink must never redirect materialized lockfile writes."""

    trusted_parent = tmp_path / "trusted-parent"
    redirected_parent = tmp_path / "redirected-parent"
    trusted_parent.mkdir()
    redirected_parent.mkdir()
    symlink_parent = trusted_parent / "attacker-controlled"
    symlink_parent.symlink_to(redirected_parent, target_is_directory=True)
    output_dir = symlink_parent / "materialized-locks"

    monkeypatch.setattr(materializer, "base_npm_projects", lambda *_args: [])
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])

    with pytest.raises(ValueError, match="symlink"):
        materializer.materialize(tmp_path, "a" * 40, output_dir)
    assert not (redirected_parent / "materialized-locks").exists()


def test_materialize_rejects_regular_file_output_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A regular-file path component must not be traversed as an output directory."""

    regular_parent = tmp_path / "regular-parent"
    regular_parent.write_text("not a directory\n", encoding="utf-8")
    output_dir = regular_parent / "materialized-locks"

    monkeypatch.setattr(materializer, "base_npm_projects", lambda *_args: [])
    monkeypatch.setattr(materializer, "base_pnpm_projects", lambda *_args: [])

    with pytest.raises(ValueError, match="path component must be a directory"):
        materializer.materialize(tmp_path, "a" * 40, output_dir)
