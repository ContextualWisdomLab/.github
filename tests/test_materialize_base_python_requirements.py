from __future__ import annotations

import ast
import hashlib
import io
import json
import runpy
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer
from tests.conftest import FakeHttpResponse


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
    assert (output / "vcs-manifest.json").read_text(encoding="utf-8") == "[]\n"


def test_materializes_changed_head_hash_lock_instead_of_stale_base(
    tmp_path: Path,
) -> None:
    """A changed exact-head lock replaces the stale base lock in the image context."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "requirements-quality.txt").write_text(
        "demo==1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (repo / "requirements-quality.txt").write_text(
        "demo==1 --hash=sha256:" + ("a" * 64) + "\n"
        "demo-platform==2 --hash=sha256:" + ("b" * 64) + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    head_sha = git(repo, "rev-parse", "HEAD")

    manifest = materializer.materialize(
        repo, base_sha, tmp_path / "output", head_sha=head_sha
    )

    assert manifest == [
        {"file": "requirements-000.txt", "source": "requirements-quality.txt"}
    ]
    assert (
        (tmp_path / "output" / "requirements-000.txt").read_text(encoding="utf-8")
        == (repo / "requirements-quality.txt").read_text(encoding="utf-8")
    )


def test_rejects_changed_head_lock_without_complete_hash_pins(tmp_path: Path) -> None:
    """An unbounded current-head lock cannot enter the networked image context."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "requirements-quality.txt").write_text(
        "demo==1 --hash=sha256:" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (repo / "requirements-quality.txt").write_text("untrusted==9\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "unbounded head")
    head_sha = git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="current-head Python lock"):
        materializer.materialize(
            repo, base_sha, tmp_path / "output", head_sha=head_sha
        )


def test_candidate_lock_blobs_rejects_invalid_revision_sha(tmp_path: Path) -> None:
    """Current-head discovery refuses symbolic or abbreviated revisions."""
    with pytest.raises(ValueError, match="revision SHA must be exactly 40"):
        materializer._candidate_lock_blobs(tmp_path, "HEAD")


def test_materialize_rejects_invalid_head_sha_before_git_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Materialization validates the exact HEAD revision before reading Git."""
    monkeypatch.setattr(
        materializer,
        "_git",
        lambda *_args: pytest.fail("invalid HEAD must be rejected before Git access"),
    )

    with pytest.raises(ValueError, match="head SHA must be exactly 40"):
        materializer.materialize(
            tmp_path, "a" * 40, tmp_path / "output", head_sha="HEAD"
        )


def test_candidate_lock_blobs_skips_non_lock_blobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEAD discovery considers only eligible regular lock paths."""
    tree = (
        b"100644 blob "
        + b"a" * 40
        + b"\tREADME.md\0"
        + b"100644 blob "
        + b"b" * 40
        + b"\trequirements.txt\0"
    )
    monkeypatch.setattr(
        materializer,
        "_git",
        lambda _repo, *args: (
            tree
            if args[0] == "ls-tree"
            else b"demo==1 --hash=sha256:" + b"a" * 64
            if args[0] == "show"
            else b"b" * 40
        ),
    )

    assert list(materializer._candidate_lock_blobs(tmp_path, "c" * 40)) == [
        "requirements.txt"
    ]


def test_candidate_lock_blobs_rejects_invalid_blob_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed Git blob identity cannot authenticate a HEAD lock."""
    tree = b"100644 blob " + b"a" * 40 + b"\trequirements.txt\0"

    def fake_git(_repo: Path, *args: str) -> bytes:
        if args[0] == "ls-tree":
            return tree
        if args[0] == "show":
            return b"demo==1 --hash=sha256:" + b"a" * 64
        return b"not-a-sha"

    monkeypatch.setattr(materializer, "_git", fake_git)

    with pytest.raises(RuntimeError, match="invalid blob SHA"):
        materializer._candidate_lock_blobs(tmp_path, "c" * 40)


def test_select_python_locks_handles_new_removed_and_unchanged_head_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selection adds new locks, removes deleted locks, and preserves equal blobs."""
    new_content = b"new==1 --hash=sha256:" + b"b" * 64
    monkeypatch.setattr(
        materializer,
        "_candidate_lock_blobs",
        lambda _repo, _head: {"requirements-new.txt": (new_content, "b" * 40)},
    )
    assert materializer._select_python_locks(
        tmp_path,
        "a" * 40,
        [],
        "c" * 40,
    ) == [("requirements-new.txt", new_content)]

    monkeypatch.setattr(
        materializer,
        "_candidate_lock_blobs",
        lambda _repo, _head: {
            "requirements-unpinned.txt": (b"untrusted==9\n", "f" * 40)
        },
    )
    assert materializer._select_python_locks(
        tmp_path,
        "a" * 40,
        [],
        "c" * 40,
    ) == []

    monkeypatch.setattr(materializer, "_candidate_lock_blobs", lambda *_args: {})
    old_content = b"old==1 --hash=sha256:" + b"c" * 64
    assert materializer._select_python_locks(
        tmp_path,
        "a" * 40,
        [("requirements-old.txt", old_content)],
        "c" * 40,
    ) == []

    same_content = b"same==1 --hash=sha256:" + b"d" * 64
    monkeypatch.setattr(
        materializer,
        "_candidate_lock_blobs",
        lambda *_args: {"requirements-same.txt": (same_content, "e" * 40)},
    )
    monkeypatch.setattr(materializer, "_git", lambda *_args: b"e" * 40)
    assert materializer._select_python_locks(
        tmp_path,
        "a" * 40,
        [("requirements-same.txt", same_content)],
        "c" * 40,
    ) == [("requirements-same.txt", same_content)]


def test_changed_python_lock_accepts_an_empty_dependency_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing every dependency drops the stale base lock without publishing one."""
    old_content = b"old==1 --hash=sha256:" + b"a" * 64 + b"\n"
    monkeypatch.setattr(
        materializer,
        "_candidate_lock_blobs",
        lambda _repo, _head: {
            "requirements.txt": (b"# Dependencies intentionally removed.\n", "b" * 40)
        },
    )
    monkeypatch.setattr(materializer, "_git", lambda *_args: b"a" * 40)

    assert materializer._select_python_locks(
        tmp_path,
        "a" * 40,
        [("requirements.txt", old_content)],
        "b" * 40,
    ) == []


def test_materializes_exact_vcs_sources_in_a_separate_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VCS source pins never enter a pip --require-hashes input file."""
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.invalid")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base")
    base_sha = git(repository, "rev-parse", "HEAD")
    hash_lock = b"demo==1 --hash=sha256:" + b"a" * 64 + b"\n"
    vcs_sources = [
        {
            "package": "rankweave",
            "import_name": "rankweave",
            "repository": "RankWeave",
            "commit": "61c49c50d3b4a24fc9bd7c6d3a7f2f4ba19d7be6",
            "source": "uv.lock",
        }
    ]
    monkeypatch.setattr(
        materializer,
        "_base_python_inputs",
        lambda *_args: ([("uv.lock", hash_lock)], vcs_sources),
    )

    output = tmp_path / "output"
    materializer.materialize(repository, base_sha, output)

    assert (output / "requirements-000.txt").read_bytes() == hash_lock
    assert (
        json.loads((output / "vcs-manifest.json").read_text(encoding="utf-8"))
        == vcs_sources
    )


def test_base_inputs_preserve_a_vcs_only_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source-only uv closure is useful even without registry requirements."""
    tree = (
        b"100644 blob " + b"a" * 40 + b"\tpyproject.toml\0"
        b"100644 blob " + b"b" * 40 + b"\tuv.lock\0"
    )
    dependency = {
        "package": "rankweave",
        "import_name": "rankweave",
        "repository": "RankWeave",
        "commit": "61c49c50d3b4a24fc9bd7c6d3a7f2f4ba19d7be6",
    }
    monkeypatch.setattr(materializer, "_git", lambda *_args: tree)
    monkeypatch.setattr(
        materializer,
        "_export_uv_lock",
        lambda *_args: (b"", [dependency]),
    )

    locks, vcs_sources = materializer._base_python_inputs(tmp_path, "a" * 40)

    assert locks == []
    assert vcs_sources == [{**dependency, "source": "uv.lock"}]


def test_base_inputs_reject_conflicting_vcs_revisions_across_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Separate uv projects cannot select ambiguous revisions of one source."""
    tree = b"".join(
        b"100644 blob " + bytes(character, "ascii") * 40 + b"\t" + path + b"\0"
        for character, path in (
            ("a", b"first/pyproject.toml"),
            ("b", b"first/uv.lock"),
            ("c", b"second/pyproject.toml"),
            ("d", b"second/uv.lock"),
        )
    )
    monkeypatch.setattr(materializer, "_git", lambda *_args: tree)

    def export(_repo: Path, _sha: str, lock_path: str):
        commit = "a" * 40 if lock_path.startswith("first/") else "b" * 40
        return b"", [{"package": "demo", "repository": "demo", "commit": commit}]

    monkeypatch.setattr(materializer, "_export_uv_lock", export)

    with pytest.raises(RuntimeError, match="conflicting commits"):
        materializer._base_python_inputs(tmp_path, "a" * 40)


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
    requirements_dir = repo / "requirements"
    requirements_dir.mkdir()
    (requirements_dir / "ci.txt").write_text(
        "pytest==9 --hash=sha256:" + ("c" * 64) + "\n",
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
        "requirements/ci.txt",
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
    assert materializer._is_candidate_lock_path(
        materializer.pathlib.PurePosixPath("requirements/ci.txt")
    )
    assert materializer._is_candidate_lock_path(
        materializer.pathlib.PurePosixPath("service/requirements/package.txt")
    )
    assert not materializer._is_candidate_lock_path(
        materializer.pathlib.PurePosixPath("service/config/ci.txt")
    )


def test_hash_pin_detection_includes_pinned_and_excludes_unpinned_or_empty() -> None:
    """Only fully hash-pinned, non-empty lock content is materialized."""
    assert not materializer._is_hash_pinned(b"# comment only\n\n")
    assert not materializer._is_hash_pinned(b"--require-hashes\ndemo==1\n")
    assert materializer._is_hash_pinned(b"demo==1 --hash=sha256:" + b"a" * 64 + b"\n")
    assert materializer._is_hash_pinned(b"-r requirements-other.txt\n")
    assert materializer._is_hash_pinned(b"-r other-hashes.txt\n")
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
    assert not materializer._is_bounded_requirement_include("-r pyproject.toml")
    assert not materializer._is_hash_pinned(b"untrusted==1\n")
    # uv export / pip-compile multi-line continuation format (spec, then --hash= lines).
    assert materializer._is_hash_pinned(
        b"foo==1 \\\n    --hash=sha256:"
        + b"a" * 64
        + b" \\\n    --hash=sha256:"
        + b"b" * 64
        + b"\n"
    )


def test_materialized_bounded_include_is_resolvable_by_pip(tmp_path: Path) -> None:
    """A safe base-owned include survives flattening and pip hash preflight."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")

    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    wheel = wheel_dir / "demo-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("demo/__init__.py", "__version__ = '1'\n")
        archive.writestr(
            "demo-1.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo\nVersion: 1\n",
        )
        archive.writestr(
            "demo-1.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: TEPP-test\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("demo-1.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

    (repo / "requirements.txt").write_text(
        "-r other-hashes.txt\n", encoding="utf-8"
    )
    (repo / "other-hashes.txt").write_text(
        f"--require-hashes\ndemo==1 --hash=sha256:{digest}\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output)
    assert manifest == [{"file": "requirements-000.txt", "source": "requirements.txt"}]
    assert (output / "requirements-000.txt").read_text(encoding="utf-8") == (
        "-r includes-000/other-hashes.txt\n"
    )
    assert (output / "includes-000" / "other-hashes.txt").is_file()

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(wheel_dir),
            "--require-hashes",
            "-r",
            str(output / "requirements-000.txt"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_materialization_rejects_missing_or_nested_include(tmp_path: Path) -> None:
    """Includes must resolve to direct complete hash closures in the exact base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "requirements.txt").write_text("-r child.txt\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "missing")
    missing_sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="not a regular base blob"):
        materializer.materialize(repo, missing_sha, tmp_path / "missing-output")

    (repo / "child.txt").write_text("-r grandchild.txt\n", encoding="utf-8")
    (repo / "grandchild.txt").write_text(
        "demo==1 --hash=sha256:" + ("d" * 64) + "\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "nested")
    nested_sha = git(repo, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="must contain only exact SHA-256 pins"):
        materializer.materialize(repo, nested_sha, tmp_path / "nested-output")

    with pytest.raises(RuntimeError, match="base lock requirements.txt is not valid UTF-8"):
        materializer._rewrite_materialized_includes(
            b"\xff", "includes-000", "requirements.txt"
        )


@pytest.mark.parametrize(
    ("head_child", "expected_child", "expected_error"),
    [
        (
            "demo==2 --hash=sha256:" + ("e" * 64) + "\n",
            "demo==2 --hash=sha256:" + ("e" * 64) + "\n",
            None,
        ),
        (
            "demo==1 --hash=sha256:" + ("d" * 64) + "\n",
            "demo==1 --hash=sha256:" + ("d" * 64) + "\n",
            None,
        ),
        (None, None, "not a regular current-head blob"),
        ("untrusted==2\n", None, "current-head bounded include"),
    ],
)
def test_materialization_revalidates_includes_at_current_head(
    tmp_path: Path,
    head_child: str | None,
    expected_child: str | None,
    expected_error: str | None,
) -> None:
    """An unchanged parent cannot retain stale or unsafe HEAD include content."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "requirements.txt").write_text("-r child.txt\n", encoding="utf-8")
    (repo / "child.txt").write_text(
        "demo==1 --hash=sha256:" + ("d" * 64) + "\n", encoding="utf-8"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    child = repo / "child.txt"
    if head_child is None:
        child.unlink()
    else:
        child.write_text(head_child, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "--allow-empty", "-m", "head")
    head_sha = git(repo, "rev-parse", "HEAD")

    if expected_error is not None:
        with pytest.raises(RuntimeError, match=expected_error):
            materializer.materialize(
                repo, base_sha, tmp_path / "output", head_sha=head_sha
            )
        return

    materializer.materialize(
        repo, base_sha, tmp_path / "output", head_sha=head_sha
    )
    assert (tmp_path / "output" / "includes-000" / "child.txt").read_text(
        encoding="utf-8"
    ) == expected_child


def test_included_head_lock_requires_head_tree_paths(tmp_path: Path) -> None:
    """Current-head include validation cannot run without its exact tree paths."""
    with pytest.raises(ValueError, match="current-head regular paths are required"):
        materializer._included_base_lock_blobs(
            tmp_path,
            "a" * 40,
            "requirements.txt",
            b"-r child.txt\n",
            {"child.txt"},
            head_sha="b" * 40,
        )


def test_bounded_repair_driver_runs_against_a_staged_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one-shot repair driver applies every guarded edit in isolation."""
    repository_root = Path(__file__).parents[1]
    relative_files = (
        "scripts/ci/repair_pr827_coderabbit_comments.py",
        "scripts/ci/materialize_base_python_requirements.py",
        "tests/test_materialize_base_python_requirements.py",
        "tests/test_opencode_rust_coverage_toolchain_contract.py",
        "docs/doctoring/opencode-rust-coverage-runtime-boundary.md",
        ".github/workflows/opencode-review-dispatch.yml",
        "CHANGELOG.md",
    )
    for relative_file in relative_files:
        source = repository_root / relative_file
        destination = tmp_path / relative_file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace(
            "## [Unreleased]\n",
            "## [Unreleased]\n\n"
            "- Materialized base Python locks only when every package line is an exact "
            "SHA-256 pin or a bounded relative `-r`/`--requirement` include. A lone "
            "`--require-hashes` directive, a dotted include such as `./lock.txt`, or "
            "`-r other-hashes.txt` no longer enters the trusted build context.\n",
            1,
        ),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    runpy.run_path(
        str(repository_root / "scripts/ci/repair_pr827_coderabbit_comments.py"),
        run_name="__main__",
    )

    materializer_source = (
        tmp_path / "scripts/ci/materialize_base_python_requirements.py"
    ).read_text(encoding="utf-8")
    assert "def _bounded_requirement_include_target(" in materializer_source
    assert "def _included_base_lock_blobs(" in materializer_source
    assert "includes-000/" in (
        tmp_path / "tests/test_materialize_base_python_requirements.py"
    ).read_text(encoding="utf-8")
    assert "Apache-2.0 WITH LLVM-exception" in (
        tmp_path / "docs/doctoring/opencode-rust-coverage-runtime-boundary.md"
    ).read_text(encoding="utf-8")

    script_path = repository_root / "scripts/ci/repair_pr827_coderabbit_comments.py"
    tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace: dict[str, object] = {"Path": Path}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=definitions, type_ignores=[])),
            str(script_path),
            "exec",
        ),
        namespace,
    )
    replace_once = namespace["replace_once"]
    replace_between = namespace["replace_between"]
    once_file = tmp_path / "once.txt"
    once_file.write_text("old", encoding="utf-8")
    replace_once(str(once_file), "old", "new")  # type: ignore[operator]
    assert once_file.read_text(encoding="utf-8") == "new"
    with pytest.raises(SystemExit, match="expected one replacement marker"):
        replace_once(str(once_file), "missing", "other")  # type: ignore[operator]
    repeated_file = tmp_path / "repeated.txt"
    repeated_file.write_text("oldold", encoding="utf-8")
    replace_once(  # type: ignore[operator]
        str(repeated_file), "old", "new", allow_repeated=True
    )
    assert repeated_file.read_text(encoding="utf-8") == "newold"

    between_file = tmp_path / "between.txt"
    between_file.write_text("START old END", encoding="utf-8")
    replace_between(str(between_file), "START", "END", "START new ")  # type: ignore[operator]
    assert between_file.read_text(encoding="utf-8") == "START new END"
    replace_between(str(between_file), "MISSING", "END", "START new ")  # type: ignore[operator]
    before_file = tmp_path / "before.txt"
    before_file.write_text("ANCHOR", encoding="utf-8")
    insert_before = namespace["insert_before"]
    insert_before(str(before_file), "ANCHOR", "PREFIX ")  # type: ignore[operator]
    assert before_file.read_text(encoding="utf-8") == "PREFIX ANCHOR"
    insert_before(str(before_file), "ANCHOR", "PREFIX ")  # type: ignore[operator]
    with pytest.raises(SystemExit, match="expected one insertion anchor"):
        insert_before(str(before_file), "MISSING", "OTHER ")  # type: ignore[operator]
    after_file = tmp_path / "after.txt"
    after_file.write_text("ANCHOR", encoding="utf-8")
    insert_after = namespace["insert_after"]
    insert_after(str(after_file), "ANCHOR", " SUFFIX")  # type: ignore[operator]
    assert after_file.read_text(encoding="utf-8") == "ANCHOR SUFFIX"
    insert_after(str(after_file), "ANCHOR", " SUFFIX")  # type: ignore[operator]
    with pytest.raises(SystemExit, match="expected one insertion anchor"):
        insert_after(str(after_file), "MISSING", " OTHER")  # type: ignore[operator]
    between_file.write_text("START old START END", encoding="utf-8")
    with pytest.raises(SystemExit, match="start marker missing or ambiguous"):
        replace_between(str(between_file), "START", "END", "replacement")  # type: ignore[operator]
    between_file.write_text("START old", encoding="utf-8")
    with pytest.raises(SystemExit, match="end marker missing"):
        replace_between(str(between_file), "START", "END", "replacement")  # type: ignore[operator]


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
        "Materialized trusted Python lock backend/requirements-hashes.txt "
        "as requirements-000.txt." in capsys.readouterr().out
    )


def test_main_forwards_optional_head_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI passes an explicitly supplied HEAD revision to materialization."""
    captured: dict[str, str] = {}

    def fake_materialize(
        _repo_root: Path,
        _base_sha: str,
        _output_dir: Path,
        *,
        head_sha: str,
    ) -> list[dict[str, str]]:
        captured["head_sha"] = head_sha
        return []

    monkeypatch.setattr(materializer, "materialize", fake_materialize)

    assert (
        materializer.main(
            [
                "--repo-root",
                str(tmp_path),
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
                "--output-dir",
                str(tmp_path / "output"),
            ]
        )
        == 0
    )
    assert captured == {"head_sha": "b" * 40}


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
        "any exact VCS source pins are listed in vcs-manifest.json"
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


@pytest.mark.parametrize(
    ("head_registry", "head_vcs"),
    [
        (
            b"head-dep==2 --hash=sha256:" + b"b" * 64 + b"\n",
            [],
        ),
        (
            b"",
            [
                {
                    "package": "head-source",
                    "import_name": "head_source",
                    "repository": "head-repository",
                    "commit": "b" * 40,
                }
            ],
        ),
        (
            b"head-dep==2 --hash=sha256:" + b"b" * 64 + b"\n",
            [
                {
                    "package": "head-source",
                    "import_name": "head_source",
                    "repository": "head-repository",
                    "commit": "b" * 40,
                }
            ],
        ),
    ],
)
def test_changed_uv_lock_replaces_base_registry_and_vcs_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head_registry: bytes,
    head_vcs: list[dict[str, str]],
) -> None:
    """A changed exact-head uv project replaces every base export component."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    (repo / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    git(repo, "add", "uv.lock")
    git(repo, "commit", "-m", "head")
    head_sha = git(repo, "rev-parse", "HEAD")

    base_registry = b"base-dep==1 --hash=sha256:" + b"a" * 64 + b"\n"
    base_vcs = [
        {
            "package": "base-source",
            "import_name": "base_source",
            "repository": "base-repository",
            "commit": "a" * 40,
        }
    ]

    def export(_repo: Path, revision: str, _lock_path: str):
        return (
            (base_registry, base_vcs)
            if revision == base_sha
            else (head_registry, head_vcs)
        )

    monkeypatch.setattr(materializer, "_export_uv_lock", export)

    output = tmp_path / "output"
    manifest = materializer.materialize(repo, base_sha, output, head_sha=head_sha)

    expected_manifest = (
        [{"file": "requirements-000.txt", "source": "uv.lock"}]
        if head_registry
        else []
    )
    assert manifest == expected_manifest
    if head_registry:
        assert (output / "requirements-000.txt").read_bytes() == head_registry
    assert json.loads((output / "vcs-manifest.json").read_text()) == [
        {**dependency, "source": "uv.lock"} for dependency in head_vcs
    ]


def test_changed_uv_lock_does_not_require_a_base_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repaired HEAD uv project replaces a base project that no longer exports."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    (repo / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    git(repo, "add", "uv.lock")
    git(repo, "commit", "-m", "repair uv lock")
    head_sha = git(repo, "rev-parse", "HEAD")
    head_registry = b"head-dep==2 --hash=sha256:" + b"b" * 64 + b"\n"

    def export(_repo: Path, revision: str, _lock_path: str):
        if revision == base_sha:
            raise RuntimeError("base uv lock is stale")
        return head_registry, []

    monkeypatch.setattr(materializer, "_export_uv_lock", export)

    output = tmp_path / "output"
    assert materializer.materialize(repo, base_sha, output, head_sha=head_sha) == [
        {"file": "requirements-000.txt", "source": "uv.lock"}
    ]
    assert (output / "requirements-000.txt").read_bytes() == head_registry


def test_deleted_uv_lock_removes_base_registry_and_vcs_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting a uv project cannot leave its base dependency export installed."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    (repo / "uv.lock").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "delete uv lock")
    head_sha = git(repo, "rev-parse", "HEAD")
    base_registry = b"base-dep==1 --hash=sha256:" + b"a" * 64 + b"\n"
    base_vcs = [
        {
            "package": "base-source",
            "import_name": "base_source",
            "repository": "base-repository",
            "commit": "a" * 40,
        }
    ]
    monkeypatch.setattr(
        materializer,
        "_export_uv_lock",
        lambda _repo, _revision, _path: (base_registry, base_vcs),
    )

    output = tmp_path / "output"
    assert materializer.materialize(repo, base_sha, output, head_sha=head_sha) == []
    assert json.loads((output / "vcs-manifest.json").read_text()) == []


def test_deleted_uv_lock_does_not_require_a_base_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting a broken base uv project omits it without exporting the stale lock."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    (repo / "uv.lock").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "delete stale uv lock")
    head_sha = git(repo, "rev-parse", "HEAD")

    def fail_base_export(_repo: Path, revision: str, _lock_path: str):
        assert revision == base_sha
        raise RuntimeError("base uv lock is stale")

    monkeypatch.setattr(materializer, "_export_uv_lock", fail_base_export)

    output = tmp_path / "output"
    assert materializer.materialize(repo, base_sha, output, head_sha=head_sha) == []
    assert json.loads((output / "vcs-manifest.json").read_text()) == []


def test_unchanged_uv_lock_preserves_base_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchanged uv project stays base-bound when another file changes."""
    repo, base_sha = _uv_repo(tmp_path, with_pyproject=True)
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "unrelated head change")
    head_sha = git(repo, "rev-parse", "HEAD")
    base_registry = b"base-dep==1 --hash=sha256:" + b"a" * 64 + b"\n"
    monkeypatch.setattr(
        materializer,
        "_export_uv_lock",
        lambda _repo, _revision, _path: (base_registry, []),
    )

    output = tmp_path / "output"
    assert materializer.materialize(repo, base_sha, output, head_sha=head_sha) == [
        {"file": "requirements-000.txt", "source": "uv.lock"}
    ]
    assert (output / "requirements-000.txt").read_bytes() == base_registry


def test_changed_uv_lock_with_empty_head_export_removes_base_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid HEAD project with no third-party closure removes old inputs."""
    monkeypatch.setattr(
        materializer,
        "_export_uv_lock",
        lambda _repo, _revision, _path: None,
    )
    assert materializer._replace_changed_uv_inputs(
        tmp_path,
        "b" * 40,
        [("uv.lock", b"base")],
        [
            {
                "package": "base-source",
                "import_name": "base_source",
                "repository": "base-repository",
                "commit": "a" * 40,
                "source": "uv.lock",
            }
        ],
        {"uv.lock"},
        {"uv.lock"},
    ) == ([], [])


def test_changed_uv_lock_rejects_conflicting_replaced_vcs_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed HEAD export cannot conflict with an unchanged source pin."""
    monkeypatch.setattr(
        materializer,
        "_export_uv_lock",
        lambda _repo, _revision, _path: (
            b"",
            [
                {
                    "package": "head-source",
                    "import_name": "head_source",
                    "repository": "shared-repository",
                    "commit": "b" * 40,
                }
            ],
        ),
    )
    with pytest.raises(RuntimeError, match="conflicting commits"):
        materializer._replace_changed_uv_inputs(
            tmp_path,
            "b" * 40,
            [],
            [
                {
                    "package": "base-source",
                    "import_name": "base_source",
                    "repository": "shared-repository",
                    "commit": "a" * 40,
                    "source": "other/uv.lock",
                }
            ],
            {"uv.lock"},
            {"uv.lock"},
        )


def test_changed_uv_inputs_preserve_distinct_shared_repository_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing a uv project cannot collapse distinct owners of one revision."""
    commit = "a" * 40
    owners = [
        {
            "package": package,
            "import_name": package.replace("-", "_"),
            "repository": "shared-repository",
            "commit": commit,
        }
        for package in ("first-owner", "second-owner")
    ]
    monkeypatch.setattr(
        materializer,
        "_export_uv_lock",
        lambda _repo, _revision, _path: (b"", owners),
    )

    assert materializer._replace_changed_uv_inputs(
        tmp_path,
        "b" * 40,
        [],
        [],
        {"uv.lock"},
        {"uv.lock"},
    ) == ([], [{**owner, "source": "uv.lock"} for owner in owners])


def test_changed_uv_inputs_reject_conflicting_retained_repository_revisions(
    tmp_path: Path,
) -> None:
    """A pre-existing manifest conflict cannot survive an unrelated replacement."""
    with pytest.raises(RuntimeError, match="conflicting commits"):
        materializer._replace_changed_uv_inputs(
            tmp_path,
            "b" * 40,
            [],
            [
                {
                    "repository": "shared-repository",
                    "commit": commit,
                    "source": source,
                }
                for commit, source in (
                    ("a" * 40, "first/uv.lock"),
                    ("b" * 40, "second/uv.lock"),
                )
            ],
            {"third/uv.lock"},
            set(),
        )


@pytest.mark.parametrize(
    ("head_dependencies", "expected_source", "expected_error"),
    [
        ([], "first/uv.lock", None),
        (
            [
                {
                    "package": "shared-source",
                    "import_name": "shared_source",
                    "repository": "shared-repository",
                    "commit": "b" * 40,
                }
            ],
            None,
            "conflicting commits",
        ),
    ],
)
def test_changed_uv_project_preserves_unaffected_shared_vcs_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head_dependencies: list[dict[str, str]],
    expected_source: str | None,
    expected_error: str | None,
) -> None:
    """A collapsed VCS repository entry cannot hide an unchanged project owner."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    for project in ("first", "second"):
        project_root = repo / project
        project_root.mkdir()
        (project_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
        (project_root / "pyproject.toml").write_text(
            f"[project]\nname = '{project}'\nversion = '0'\n", encoding="utf-8"
        )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")

    (repo / "second" / "uv.lock").write_text("version = 2\n", encoding="utf-8")
    git(repo, "add", "second/uv.lock")
    git(repo, "commit", "-m", "change second uv lock")
    head_sha = git(repo, "rev-parse", "HEAD")
    shared_dependency = {
        "package": "shared-source",
        "import_name": "shared_source",
        "repository": "shared-repository",
        "commit": "a" * 40,
    }

    def export(_repo: Path, revision: str, _lock_path: str):
        return (
            (b"", [shared_dependency])
            if revision == base_sha
            else (b"", head_dependencies)
        )

    monkeypatch.setattr(materializer, "_export_uv_lock", export)

    if expected_error is not None:
        with pytest.raises(RuntimeError, match=expected_error):
            materializer.materialize(
                repo, base_sha, tmp_path / "output", head_sha=head_sha
            )
        return

    output = tmp_path / "output"
    assert materializer.materialize(repo, base_sha, output, head_sha=head_sha) == []
    assert json.loads((output / "vcs-manifest.json").read_text()) == [
        {**shared_dependency, "source": expected_source}
    ]


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
