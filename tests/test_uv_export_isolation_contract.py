"""Behavioral isolation and output contracts for trusted ``uv export``."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def test_uv_export_runs_with_a_bounded_isolated_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient runner configuration cannot select export behavior or cache state."""
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    result = materializer._run_uv_export(tmp_path, "/trusted/uv")

    assert result.returncode == 0
    assert observed["command"] == [
        "/trusted/uv",
        "export",
        "--frozen",
        "--offline",
        "--no-cache",
        "--no-progress",
        "--color",
        "never",
        "--no-emit-project",
        "--no-editable",
        "--format",
        "requirements-txt",
    ]
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["check"] is False
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE

    environment = kwargs["env"]
    assert environment == {
        "HOME": str(tmp_path / ".uv-home"),
        "NO_COLOR": "1",
        "PATH": os.defpath,
        "TMPDIR": str(tmp_path / ".uv-tmp"),
        "UV_NO_ENV_FILE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "XDG_CACHE_HOME": str(tmp_path / ".uv-cache"),
        "XDG_CONFIG_HOME": str(tmp_path / ".uv-config"),
    }
    for directory_name in (".uv-home", ".uv-tmp", ".uv-cache", ".uv-config"):
        assert (tmp_path / directory_name).is_dir()


def test_uv_export_does_not_disable_project_metadata_discovery() -> None:
    """Isolation must retain the reconstructed project's ``pyproject.toml`` input."""
    source = Path(materializer.__file__).read_text(encoding="utf-8")

    assert '"--no-config"' not in source
    assert "UV_NO_CONFIG" not in source


@pytest.mark.parametrize(
    "content",
    [
        b"--index-url https://packages.invalid/simple --hash=sha256:" + b"a" * 64 + b"\n",
        b"demo @ file:///tmp/demo --hash=sha256:" + b"a" * 64 + b"\n",
        b"demo==1 --hash=sha512:" + b"a" * 128 + b"\n",
        b"demo==1 --hash=sha256:abcd\n",
    ],
)
def test_uv_export_rejects_non_package_or_non_sha256_lines(content: bytes) -> None:
    """An option, local reference, wrong algorithm, or short digest is not a lock pin."""
    assert materializer._is_fully_hash_pinned_export(content) is False


def test_uv_export_accepts_exact_package_pins_with_markers_and_multiple_hashes() -> None:
    """A normalized exact requirement with SHA-256 hashes remains exportable."""
    content = (
        b"demo-extra[fast]==1.2.3 ; python_version >= '3.12' \\\n"
        b"    --hash=sha256:" + b"a" * 64 + b" \\\n"
        b"    --hash=sha256:" + b"b" * 64 + b"\n"
    )

    assert materializer._is_fully_hash_pinned_export(content) is True


def test_uv_export_accepts_hash_pinned_organization_archive_as_registry_lock() -> None:
    """A trusted HTTPS archive with a complete hash remains a pip lock entry."""
    content = (
        b"fast-mlsirm @ https://github.com/ContextualWisdomLab/fast-mlsirm/"
        b"archive/refs/tags/v0.9.1.tar.gz ; python_full_version >= '3.12' \\\n"
        b"    --hash=sha256:" + b"a" * 64 + b"\n"
    )

    registry, vcs_sources, archive_sources = materializer._partition_uv_export(content)

    assert materializer._is_fully_hash_pinned_export(content) is True
    assert registry == b""
    assert vcs_sources == []
    assert archive_sources == [
        {
            "package": "fast-mlsirm",
            "url": "https://github.com/ContextualWisdomLab/fast-mlsirm/archive/refs/tags/v0.9.1.tar.gz",
            "hashes": ["a" * 64],
            "marker": "python_full_version >= '3.12'",
        }
    ]


def test_uv_export_rejects_organization_archive_without_complete_sha256_hash() -> None:
    """Organization archives must carry a complete SHA-256 hash before partitioning."""
    content = (
        b"demo @ https://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz "
        b"--hash=sha256:abcd\n"
    )

    with pytest.raises(ValueError, match="complete SHA-256 hashes"):
        materializer._partition_uv_export(content)


def test_uv_export_rejects_conflicting_hashes_for_one_archive_url() -> None:
    """One archive URL cannot be admitted with two different digests."""
    url = "https://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz"
    content = (
        f"demo @ {url} --hash=sha256:{'a' * 64}\n"
        f"demo @ {url} --hash=sha256:{'b' * 64}\n"
    ).encode()

    with pytest.raises(ValueError, match="conflicting hashes"):
        materializer._partition_uv_export(content)


def test_uv_export_keeps_same_archive_url_for_distinct_markers() -> None:
    """Conditional alternatives sharing a URL remain separate requirements."""
    url = "https://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz"
    content = (
        f"demo @ {url} ; python_version < '3.10' --hash=sha256:{'a' * 64}\n"
        f"demo @ {url} ; python_version >= '3.10' --hash=sha256:{'a' * 64}\n"
    ).encode()

    _registry, _vcs_sources, archive_sources = materializer._partition_uv_export(content)

    assert [archive["marker"] for archive in archive_sources] == [
        "python_version < '3.10'",
        "python_version >= '3.10'",
    ]


def test_uv_export_rejects_different_hashes_for_same_url_across_markers() -> None:
    """Conditional alternatives cannot change the immutable archive payload."""
    url = "https://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz"
    content = (
        f"demo @ {url} ; python_version < '3.10' --hash=sha256:{'a' * 64}\n"
        f"demo @ {url} ; python_version >= '3.10' --hash=sha256:{'b' * 64}\n"
    ).encode()

    with pytest.raises(ValueError, match="conflicting hashes"):
        materializer._partition_uv_export(content)


def test_uv_export_partitions_hashes_and_exact_organization_vcs_sources() -> None:
    """An immutable organization source pin is separated from pip hash locks."""
    content = (
        b"demo==1.2.3 --hash=sha256:" + b"a" * 64 + b"\n"
        b"rank.weave-extra[GPU] @ git+https://github.com/ContextualWisdomLab/RankWeave.git@"
        b"61c49c50d3b4a24fc9bd7c6d3a7f2f4ba19d7be6\n"
    )

    registry, vcs_sources, archive_sources = materializer._partition_uv_export(content)

    assert registry == b"demo==1.2.3 --hash=sha256:" + b"a" * 64 + b"\n"
    assert vcs_sources == [
        {
            "package": "rank.weave-extra[GPU]",
            "import_name": "rank_weave_extra",
            "repository": "RankWeave",
            "commit": "61c49c50d3b4a24fc9bd7c6d3a7f2f4ba19d7be6",
        }
    ]
    assert archive_sources == []


@pytest.mark.parametrize(
    "requirement",
    [
        "demo @ git+http://github.com/ContextualWisdomLab/demo.git@" + "a" * 40,
        "demo @ git+https://github.com/other/demo.git@" + "a" * 40,
        "demo @ git+https://github.com/ContextualWisdomLab/demo.git@main",
        "demo @ git+https://github.com/ContextualWisdomLab/demo.git@"
        + "a" * 40
        + "#subdirectory=python",
    ],
)
def test_uv_export_rejects_unbounded_vcs_sources(requirement: str) -> None:
    """Only the exact organization HTTPS origin and a full commit are accepted."""
    with pytest.raises(ValueError, match="unsupported dependency"):
        materializer._partition_uv_export(f"{requirement}\n".encode())


@pytest.mark.parametrize(
    "requirement",
    [
        "demo @ http://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz",
        "demo @ https://github.com/other/demo/archive/v1.tar.gz",
        "demo @ https://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz?download=1",
        "demo @ https://github.com/ContextualWisdomLab/demo/archive/v1.tar.gz#fragment",
        "demo @ https://github.com/ContextualWisdomLab/demo/archive/../v1.tar.gz",
    ],
)
def test_uv_export_rejects_unbounded_archive_sources(requirement: str) -> None:
    """Only archive URLs from the exact organization origin are accepted."""
    with pytest.raises(ValueError, match="unsupported dependency"):
        materializer._partition_uv_export(
            f"{requirement} --hash=sha256:{'a' * 64}\n".encode()
        )


def test_uv_export_rejects_conflicting_commits_for_one_repository() -> None:
    """One import path cannot ambiguously combine two repository revisions."""
    with pytest.raises(ValueError, match="conflicting commits"):
        materializer._partition_uv_export(
            (
                "first @ git+https://github.com/ContextualWisdomLab/demo.git@"
                + "a" * 40
                + "\nsecond @ git+https://github.com/ContextualWisdomLab/Demo.git@"
                + "b" * 40
                + "\n"
            ).encode()
        )


def test_tracked_pyproject_read_failure_is_not_misclassified_as_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A present sibling metadata blob that cannot be read must fail closed."""
    tree = (
        b"100644 blob " + b"a" * 40 + b"\tpyproject.toml\0"
        b"100644 blob " + b"b" * 40 + b"\tuv.lock\0"
    )

    def fake_git(_repo_root: Path, *args: str) -> bytes:
        if args[0] == "ls-tree":
            return tree
        if args[0] == "show" and args[1].endswith(":uv.lock"):
            return b"version = 1\n"
        if args[0] == "show" and args[1].endswith(":pyproject.toml"):
            raise RuntimeError("tracked metadata blob could not be read")
        raise AssertionError(args)

    monkeypatch.setattr(materializer, "_git", fake_git)
    monkeypatch.setattr(
        materializer,
        "_install_trusted_uv",
        lambda: (_ for _ in ()).throw(AssertionError("uv must not start")),
    )

    with pytest.raises(RuntimeError, match="tracked metadata blob could not be read"):
        materializer.base_hash_locks(tmp_path, "a" * 40)
