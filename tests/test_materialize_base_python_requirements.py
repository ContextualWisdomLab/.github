from __future__ import annotations

import hashlib
import io
import runpy
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer
from tests.conftest import FakeHttpResponse


def _simulate_linux_x86_64_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let installer verification tests run on a non-Linux developer host."""
    monkeypatch.setattr(materializer.sys, "platform", "linux")
    monkeypatch.setattr(materializer.platform, "machine", lambda: "x86_64")
    materializer._install_trusted_uv.cache_clear()


def git(repo: Path, *args: str) -> str:
    """Run git in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _created_tool_directory(path: Path) -> str:
    """Create the directory normally returned by ``tempfile.mkdtemp``."""
    path.mkdir(mode=0o700)
    return str(path)


def _force_linux_x86_64_installer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the installer path that GitHub-hosted linux x86_64 runners use."""
    monkeypatch.setattr(materializer.sys, "platform", "linux")
    monkeypatch.setattr(materializer.platform, "machine", lambda: "x86_64")
    materializer._install_trusted_uv.cache_clear()


def test_materializes_only_regular_hash_locks_from_exact_base(tmp_path: Path) -> None:
    """A PR-modified lock cannot enter the networked coverage image build context."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    backend = repo / "backend"
    backend.mkdir()
    (backend / "requirements-hashes.txt").write_text(
        "demo==1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    (repo / "requirements.lock").write_text(
        "locked==1 --hash=sha256:" + ("c" * 64) + "\n",
        encoding="utf-8",
    )
    (backend / "requirements.txt").write_text("untrusted==1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (backend / "requirements-hashes.txt").write_text(
        "changed==2 --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    (repo / "requirements.lock").write_text(
        "changed==2 --hash=sha256:" + ("d" * 64) + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [
        {
            "file": "requirements-000.txt",
            "source": "backend/requirements-hashes.txt",
        },
        {"file": "requirements-001.txt", "source": "requirements.lock"},
    ]
    assert (
        (output / "requirements-000.txt")
        .read_text(encoding="utf-8")
        .startswith("demo==1")
    )
    assert "requirements-000.txt\nrequirements-001.txt\n" == (
        output / "manifest.txt"
    ).read_text(encoding="utf-8")
    assert (
        (output / "requirements-001.txt")
        .read_text(encoding="utf-8")
        .startswith("locked==1")
    )
    assert "requirements.txt" not in (output / "manifest.json").read_text(
        encoding="utf-8"
    )


def test_materializes_hash_pinned_locks_named_beyond_the_legacy_whitelist(
    tmp_path: Path,
) -> None:
    """Hash-pinned locks in service subdirs and dev/test files are materialized.

    Discovery is content-based: a hash-pinned ``requirements-dev.txt`` under a
    service directory and a hash-pinned ``requirements-test.txt`` are installed
    for offline coverage, while a non-requirements ``uv.lock`` (excluded by name)
    and an unpinned ``requirements-extra.txt`` (excluded by content) are not.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    service = repo / "services" / "account_unification"
    service.mkdir(parents=True)
    (service / "requirements-dev.txt").write_text(
        "fastapi==1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    (repo / "requirements-test.txt").write_text(
        "hypothesis==6 --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(
        "version = 1\n[[package]]\nname = 'x'\n", encoding="utf-8"
    )
    (repo / "requirements-extra.txt").write_text("unpinned==1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert [entry["source"] for entry in manifest] == [
        "requirements-test.txt",
        "services/account_unification/requirements-dev.txt",
    ]


def test_lock_name_candidates_are_pip_requirements_files() -> None:
    """Requirements files and requirements.lock are candidates; other names are not."""
    assert materializer._is_candidate_lock_name("requirements.lock")
    assert materializer._is_candidate_lock_name("requirements-dev.txt")
    assert materializer._is_candidate_lock_name("requirements.txt")
    assert not materializer._is_candidate_lock_name(
        "requirements-opencode-review-ci-hashes.txt"
    )
    assert not materializer._is_candidate_lock_name("uv.lock")
    assert not materializer._is_candidate_lock_name("pyproject.toml")


def test_hash_pin_detection_includes_pinned_and_excludes_unpinned_or_empty() -> None:
    """Only fully hash-pinned, non-empty lock content is materialized."""
    assert not materializer._is_hash_pinned(b"# comment only\n\n")
    assert not materializer._is_hash_pinned(b"--require-hashes\ndemo==1\n")
    assert materializer._is_hash_pinned(b"demo==1 --hash=sha256:" + b"a" * 64 + b"\n")
    assert materializer._is_hash_pinned(b"-r requirements-other.txt\n")
    assert not materializer._is_hash_pinned(b"-r other-hashes.txt\n")
    assert not materializer._is_hash_pinned(b"-r ./requirements-other.txt\n")
    assert not materializer._is_hash_pinned(b"-r ../escape.txt\n")
    assert materializer._is_bounded_requirement_include(
        "--requirement requirements-other.txt"
    )
    assert not materializer._is_bounded_requirement_include("-r .")
    assert not materializer._is_bounded_requirement_include("-r -evil.txt")
    assert not materializer._is_bounded_requirement_include("-r ~evil.txt")
    assert not materializer._is_bounded_requirement_include("-r C:foo.txt")
    assert not materializer._is_bounded_requirement_include("-r foo?bar.txt")
    assert not materializer._is_bounded_requirement_include("-r foo#bar.txt")
    assert not materializer._is_bounded_requirement_include(r"-r foo\\bar.txt")
    assert not materializer._is_bounded_requirement_include("-r")
    assert not materializer._is_bounded_requirement_include("-r /abs/requirements.txt")
    assert not materializer._is_hash_pinned(b"untrusted==1\n")
    # uv export / pip-compile multi-line continuation format (spec, then --hash= lines).
    assert materializer._is_hash_pinned(
        b"foo==1 \\\n    --hash=sha256:"
        + b"a" * 64
        + b" \\\n    --hash=sha256:"
        + b"b" * 64
        + b"\n"
    )


def test_rejects_invalid_base_sha(tmp_path: Path) -> None:
    """Git options and symbolic refs cannot cross the exact-SHA boundary."""
    with pytest.raises(ValueError, match="40 hexadecimal"):
        materializer.base_hash_locks(tmp_path, "--help")


def test_git_failure_preserves_a_visible_reason(tmp_path: Path) -> None:
    """A failed read-only git command reports its operation and stderr."""
    with pytest.raises(RuntimeError, match=r"git rev-parse failed: fatal"):
        materializer._git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("tree_output", "message"),
    [
        (b"malformed\0", "malformed entry"),
        (b"100644 blob\tfile\0", "malformed metadata"),
    ],
)
def test_rejects_malformed_git_tree_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tree_output: bytes,
    message: str,
) -> None:
    """Malformed git output cannot be interpreted as a trusted lock blob."""

    def fake_git(_repo_root: Path, *_args: str) -> bytes:
        return tree_output

    monkeypatch.setattr(materializer, "_git", fake_git)

    with pytest.raises(RuntimeError, match=message):
        materializer.base_hash_locks(tmp_path, "a" * 40)


def test_rejects_symlink_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink cannot redirect trusted lock materialization outside its context."""
    target = tmp_path / "target"
    target.mkdir()
    output = tmp_path / "output"
    output.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: [])

    with pytest.raises(ValueError, match="must not be a symlink"):
        materializer.materialize(tmp_path, "a" * 40, output)


def test_main_reports_each_materialized_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI identifies the exact trusted source and generated lock name."""

    def fake_materialize(
        _repo_root: Path, _base_sha: str, _output_dir: Path
    ) -> list[dict[str, str]]:
        return [
            {
                "file": "requirements-000.txt",
                "source": "backend/requirements-hashes.txt",
            }
        ]

    monkeypatch.setattr(materializer, "materialize", fake_materialize)

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert (
        "Materialized trusted base Python lock backend/requirements-hashes.txt "
        "as requirements-000.txt." in capsys.readouterr().out
    )


def test_main_reports_when_no_locks_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI distinguishes an empty trusted base from a failed extraction."""
    monkeypatch.setattr(materializer, "materialize", lambda *_args: [])

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert (
        "No tracked hash-bearing Python requirement candidates exist"
        in capsys.readouterr().out
    )


def test_main_fails_with_the_materialization_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A materialization exception fails closed and remains diagnosable in CI."""

    def fail_materialize(_repo_root: Path, _base_sha: str, _output_dir: Path) -> None:
        raise OSError("fixture failure")

    monkeypatch.setattr(materializer, "materialize", fail_materialize)

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 1
    )
    assert (
        "::error::Could not materialize base Python locks: fixture failure"
        in capsys.readouterr().err
    )


def test_script_entrypoint_exits_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The executable script propagates the fail-closed CLI status."""
    module_path = Path(materializer.__file__)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(module_path),
            "--repo-root",
            str(tmp_path),
            "--base-sha",
            "invalid",
            "--output-dir",
            str(tmp_path / "output"),
        ],
    )

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(module_path), run_name="__main__")

    assert raised.value.code == 1


def test_skips_non_blob_tree_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Submodule/gitlink (non-blob) tree entries are skipped, never materialized."""
    blob = b"pinned==1 --hash=sha256:" + b"a" * 64 + b"\n"
    tree = (
        b"160000 commit " + b"0" * 40 + b"\tvendored-submodule\0"
        b"100644 blob " + b"1" * 40 + b"\trequirements.txt\0"
    )

    def fake_git(_repo_root: Path, *args: str) -> bytes:
        if args[0] == "ls-tree":
            return tree
        if args[0] == "show":
            return blob
        raise AssertionError(args)

    monkeypatch.setattr(materializer, "_git", fake_git)

    assert materializer.base_hash_locks(tmp_path, "a" * 40) == [
        ("requirements.txt", blob)
    ]


def _uv_repo(tmp_path: Path, *, with_pyproject: bool, lock_dir: str = "") -> tuple[Path, str]:
    """Init a fixture repo with a uv.lock (and optional pyproject.toml) at lock_dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    base = repo / lock_dir if lock_dir else repo
    base.mkdir(parents=True, exist_ok=True)
    (base / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    if with_pyproject:
        (base / "pyproject.toml").write_text(
            "[project]\nname = 'demo'\nversion = '0'\n", encoding="utf-8"
        )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def _export(returncode: int, stdout: bytes) -> subprocess.CompletedProcess[bytes]:
    """Build a fake ``uv export`` completed-process result."""
    return subprocess.CompletedProcess(["uv", "export"], returncode, stdout, b"")


def test_uv_lock_is_exported_to_a_hash_pinned_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A base uv.lock is exported via uv into a materialized hash-pinned closure."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/usr/bin/uv")
    hashed = b"demo-dep==1 --hash=sha256:" + b"a" * 64 + b"\n"
    monkeypatch.setattr(
        materializer,
        "_run_uv_export",
        lambda _work, _uv_path: _export(0, hashed),
    )

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)

    assert manifest == [{"file": "requirements-000.txt", "source": "uv.lock"}]
    assert (output / "requirements-000.txt").read_bytes() == hashed


def test_uv_lock_fails_closed_when_trusted_uv_bootstrap_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tracked project uv.lock cannot silently lose its dependency evidence."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)

    def fail_install() -> str:
        raise RuntimeError("trusted uv bootstrap failed")

    monkeypatch.setattr(materializer, "_install_trusted_uv", fail_install)

    with pytest.raises(RuntimeError, match="trusted uv bootstrap failed"):
        materializer.materialize(repo, base_sha, tmp_path / "output")


def test_uv_lock_skipped_when_pyproject_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A uv.lock without a sibling pyproject.toml at base (in a subdir) cannot be exported."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=False, lock_dir="service")

    def unexpected_install() -> str:
        raise AssertionError("orphan uv.lock must not bootstrap uv")

    monkeypatch.setattr(materializer, "_install_trusted_uv", unexpected_install)

    assert materializer.materialize(repo, base_sha, tmp_path / "output") == []


def test_uv_lock_fails_closed_when_export_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale or otherwise unexportable tracked uv.lock blocks evidence creation."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(
        materializer,
        "_run_uv_export",
        lambda _work, _uv_path: subprocess.CompletedProcess(
            ["uv", "export"], 1, b"", b"lock is stale\n"
        ),
    )

    with pytest.raises(RuntimeError, match="uv export failed.*lock is stale"):
        materializer.materialize(repo, base_sha, tmp_path / "output")


def test_uv_lock_fails_closed_when_export_is_not_hash_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nonempty uv export without hashes is rejected instead of ignored."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(
        materializer,
        "_run_uv_export",
        lambda _work, _uv_path: _export(0, b"unpinned==1\n"),
    )

    with pytest.raises(RuntimeError, match="not fully hash-pinned"):
        materializer.materialize(repo, base_sha, tmp_path / "output")


def test_uv_lock_with_empty_dependency_closure_materializes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful comment-only uv export represents a valid empty closure."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/usr/bin/uv")
    monkeypatch.setattr(
        materializer,
        "_run_uv_export",
        lambda _work, _uv_path: _export(0, b"# no third-party dependencies\n"),
    )

    assert materializer.materialize(repo, base_sha, tmp_path / "output") == []


def _trusted_uv_archive(
    binary: bytes = b"verified-uv",
    *,
    member_name: str = materializer.TRUSTED_UV_ARCHIVE_MEMBER,
    regular: bool = True,
) -> bytes:
    """Build a deterministic uv tar archive for supply-chain boundary tests."""
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as bundle:
        member = tarfile.TarInfo(member_name)
        if regular:
            member.size = len(binary)
            bundle.addfile(member, io.BytesIO(binary))
        else:
            member.type = tarfile.DIRTYPE
            bundle.addfile(member)
    return payload.getvalue()


def test_download_trusted_uv_archive_accepts_fixed_https_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The downloader returns bounded bytes from the fixed GitHub HTTPS origin."""
    payload = b"archive"
    response = FakeHttpResponse(materializer.TRUSTED_UV_ARCHIVE_URL, payload)
    monkeypatch.setattr(materializer.urllib.request, "urlopen", lambda *_a, **_k: response)

    assert materializer._download_trusted_uv_archive() == payload


def test_download_trusted_uv_archive_accepts_github_release_asset_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The official GitHub release-asset CDN remains a valid final HTTPS origin."""
    payload = b"archive"
    response = FakeHttpResponse(
        "https://release-assets.githubusercontent.com/"
        "github-production-release-asset/699532645/archive",
        payload,
    )
    monkeypatch.setattr(materializer.urllib.request, "urlopen", lambda *_a, **_k: response)

    assert materializer._download_trusted_uv_archive() == payload


def test_download_trusted_uv_archive_accepts_legacy_objects_asset_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The previous GitHub release-asset hostname remains a valid final origin."""
    payload = b"archive"
    response = FakeHttpResponse(
        "https://objects.githubusercontent.com/github-production-release-asset/1/file",
        payload,
    )
    monkeypatch.setattr(materializer.urllib.request, "urlopen", lambda *_a, **_k: response)

    assert materializer._download_trusted_uv_archive() == payload


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://example.invalid/uv.tar.gz",
        "https://user@github.com/astral-sh/uv/releases/download/0.12.1/uv.tar.gz",
        "https://:secret@github.com/astral-sh/uv/releases/download/0.12.1/uv.tar.gz",
    ],
)
def test_download_trusted_uv_archive_rejects_unsafe_redirect(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_url: str,
) -> None:
    """A redirect away from the fixed HTTPS release host fails closed."""
    response = FakeHttpResponse(unsafe_url)
    monkeypatch.setattr(materializer.urllib.request, "urlopen", lambda *_a, **_k: response)

    with pytest.raises(RuntimeError, match="redirected outside"):
        materializer._download_trusted_uv_archive()


def test_download_trusted_uv_archive_rejects_network_and_size_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network errors and oversized archives cannot enter the trusted tool path."""
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")),
    )
    with pytest.raises(RuntimeError, match="download failed"):
        materializer._download_trusted_uv_archive()

    response = FakeHttpResponse(materializer.TRUSTED_UV_ARCHIVE_URL, b"12345")
    monkeypatch.setattr(materializer.urllib.request, "urlopen", lambda *_a, **_k: response)
    monkeypatch.setattr(materializer, "TRUSTED_UV_DOWNLOAD_MAX_BYTES", 4)
    with pytest.raises(RuntimeError, match="bounded download size"):
        materializer._download_trusted_uv_archive()


def test_verified_uv_binary_accepts_exact_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact-hash archive yields only its bounded regular uv member."""
    archive = _trusted_uv_archive()
    monkeypatch.setattr(
        materializer, "TRUSTED_UV_ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest()
    )

    assert materializer._verified_uv_binary(archive) == b"verified-uv"


@pytest.mark.parametrize(
    ("archive", "error"),
    [
        (b"not-a-tar", "checksum verification failed"),
        (_trusted_uv_archive(member_name="wrong/uv"), "omitted the uv executable"),
        (_trusted_uv_archive(regular=False), "not a regular file"),
    ],
)
def test_verified_uv_binary_rejects_invalid_archives(
    archive: bytes, error: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checksum, membership, and file-type violations fail closed."""
    if error != "checksum verification failed":
        monkeypatch.setattr(
            materializer,
            "TRUSTED_UV_ARCHIVE_SHA256",
            hashlib.sha256(archive).hexdigest(),
        )
    with pytest.raises(RuntimeError, match=error):
        materializer._verified_uv_binary(archive)


def test_verified_uv_binary_rejects_parse_and_size_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt tar data and oversized executable metadata cannot be installed."""
    corrupt = b"not-a-tar"
    monkeypatch.setattr(
        materializer, "TRUSTED_UV_ARCHIVE_SHA256", hashlib.sha256(corrupt).hexdigest()
    )
    with pytest.raises(RuntimeError, match="could not be parsed"):
        materializer._verified_uv_binary(corrupt)

    archive = _trusted_uv_archive(binary=b"large")
    monkeypatch.setattr(
        materializer, "TRUSTED_UV_ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest()
    )
    monkeypatch.setattr(materializer, "TRUSTED_UV_BINARY_MAX_BYTES", 4)
    with pytest.raises(RuntimeError, match="bounded size"):
        materializer._verified_uv_binary(archive)


def test_verified_uv_binary_rejects_truncated_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncated regular member cannot satisfy the archive size receipt."""
    archive = b"archive"
    monkeypatch.setattr(
        materializer, "TRUSTED_UV_ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest()
    )

    class _Member:
        """Represent one regular member with a longer declared size."""

        size = 2

        @staticmethod
        def isfile() -> bool:
            """Return that this synthetic member is regular."""
            return True

    class _Bundle:
        """Return a deliberately truncated member stream."""

        def __enter__(self) -> "_Bundle":
            """Enter the synthetic archive context."""
            return self

        def __exit__(self, *_args: object) -> None:
            """Leave the synthetic archive context."""

        @staticmethod
        def getmember(_name: str) -> _Member:
            """Return the synthetic regular member."""
            return _Member()

        @staticmethod
        def extractfile(_member: _Member) -> io.BytesIO:
            """Return fewer bytes than the member metadata declares."""
            return io.BytesIO(b"x")

    monkeypatch.setattr(materializer.tarfile, "open", lambda *_a, **_k: _Bundle())

    with pytest.raises(RuntimeError, match="size did not match"):
        materializer._verified_uv_binary(archive)


def test_install_trusted_uv_verifies_version_and_caches_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installer writes one executable, verifies its version, and caches it."""
    _force_linux_x86_64_installer(monkeypatch)
    tool_dir = tmp_path / "uv"
    monkeypatch.setattr(
        materializer.tempfile,
        "mkdtemp",
        lambda **_kwargs: _created_tool_directory(tool_dir),
    )
    monkeypatch.setattr(materializer, "_download_trusted_uv_archive", lambda: b"archive")
    monkeypatch.setattr(materializer, "_verified_uv_binary", lambda _payload: b"binary")
    registered: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        materializer.atexit,
        "register",
        lambda *args, **_kwargs: registered.append(args),
    )
    calls = 0

    def verify(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            [], 0, b"uv 0.12.1 (x86_64-unknown-linux-gnu)\n", b""
        )

    monkeypatch.setattr(materializer.subprocess, "run", verify)

    first = materializer._install_trusted_uv()
    second = materializer._install_trusted_uv()

    assert first == second == str(tool_dir / "uv")
    assert Path(first).read_bytes() == b"binary"
    assert Path(first).stat().st_mode & 0o111
    assert calls == 1
    assert registered


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("missing binary"),
        subprocess.TimeoutExpired(["uv", "--version"], timeout=10),
    ],
)
def test_install_trusted_uv_rejects_version_process_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: OSError | subprocess.TimeoutExpired,
) -> None:
    """A missing or hung downloaded executable is removed and rejected."""
    _force_linux_x86_64_installer(monkeypatch)
    tool_dir = tmp_path / "uv"
    monkeypatch.setattr(
        materializer.tempfile,
        "mkdtemp",
        lambda **_kwargs: _created_tool_directory(tool_dir),
    )
    monkeypatch.setattr(materializer, "_download_trusted_uv_archive", lambda: b"archive")
    monkeypatch.setattr(materializer, "_verified_uv_binary", lambda _payload: b"binary")

    def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(materializer.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="executable verification failed"):
        materializer._install_trusted_uv()
    assert not tool_dir.exists()


@pytest.mark.parametrize(
    "completed",
    [
        subprocess.CompletedProcess(
            [], 0, b"uv 0.12.0 (x86_64-unknown-linux-gnu)\n", b""
        ),
        subprocess.CompletedProcess(
            [], 1, b"uv 0.12.1 (x86_64-unknown-linux-gnu)\n", b"failed"
        ),
        subprocess.CompletedProcess([], 0, b"uv 0.12.1\n", b""),
        subprocess.CompletedProcess(
            [], 0, b"uv 0.12.1 (aarch64-unknown-linux-gnu)\n", b""
        ),
    ],
)
def test_install_trusted_uv_rejects_wrong_version_or_exit_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[bytes],
) -> None:
    """Unexpected version output or a nonzero status cannot satisfy the pin."""
    _force_linux_x86_64_installer(monkeypatch)
    tool_dir = tmp_path / f"uv-{completed.returncode}-{len(completed.stdout)}"
    monkeypatch.setattr(
        materializer.tempfile,
        "mkdtemp",
        lambda **_kwargs: _created_tool_directory(tool_dir),
    )
    monkeypatch.setattr(materializer, "_download_trusted_uv_archive", lambda: b"archive")
    monkeypatch.setattr(materializer, "_verified_uv_binary", lambda _payload: b"binary")
    monkeypatch.setattr(
        materializer.subprocess,
        "run",
        lambda *_args, **_kwargs: completed,
    )

    with pytest.raises(RuntimeError, match="unexpected version or exit status"):
        materializer._install_trusted_uv()
    assert not tool_dir.exists()


def test_run_uv_export_invokes_uv_with_frozen_offline_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The uv export helper runs uv with frozen, project-excluding, offline flags."""
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, 0, b"out", b"")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)

    result = materializer._run_uv_export(tmp_path, "/usr/bin/uv")

    assert result.stdout == b"out"
    assert captured["argv"][:3] == ["/usr/bin/uv", "export", "--frozen"]
    assert "--offline" in captured["argv"]
    assert "--no-emit-project" in captured["argv"]
    assert "--no-editable" in captured["argv"]
    assert captured["cwd"] == str(tmp_path)
    assert captured["timeout"] == materializer.UV_EXPORT_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "export_error",
    [
        FileNotFoundError("uv disappeared"),
        subprocess.TimeoutExpired(["/usr/bin/uv", "export"], timeout=120),
    ],
)
def test_uv_export_process_failures_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    export_error: OSError | subprocess.TimeoutExpired,
) -> None:
    """A missing or hung trusted uv process cannot silently drop dependencies."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    monkeypatch.setattr(materializer, "_install_trusted_uv", lambda: "/usr/bin/uv")

    def fail_export(_work: Path, _uv_path: str) -> None:
        raise export_error

    monkeypatch.setattr(materializer, "_run_uv_export", fail_export)

    with pytest.raises(RuntimeError, match="could not run trusted uv export"):
        materializer.materialize(repo, base_sha, tmp_path / "output")
