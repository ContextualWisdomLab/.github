"""Tests for METADATA-patched strix-agent wheels and lock rewriting."""

from __future__ import annotations

import runpy
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.ci import rewrite_strix_agent_cryptography_bound as rewrite


ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
COMPILE = ROOT / "scripts" / "ci" / "compile_strix_ci_lock.sh"
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
VENDOR_WHEEL = (
    ROOT
    / "vendor"
    / "strix"
    / "strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl"
)
SOURCE = ROOT / "vendor" / "strix" / "SOURCE.json"
PUBLISHED_REF = ROOT / "vendor" / "strix" / "published-git-ref"


def _record_line(name: str, data: bytes) -> str:
    """Return one PEP 376 RECORD line for ``name``."""

    return f"{name},{rewrite.record_digest(data)},{len(data)}"


def _write_wheel(
    path: Path,
    metadata: str,
    *,
    extra_members: dict[str, bytes] | None = None,
    record: str | None = None,
) -> None:
    """Write a tiny wheel used as rewriter input."""

    metadata_name = "demo-1.0.dist-info/METADATA"
    record_name = "demo-1.0.dist-info/RECORD"
    init_name = "demo/__init__.py"
    members = {
        init_name: b"",
        metadata_name: metadata.encode("utf-8"),
        **(extra_members or {}),
    }
    if record is None:
        record = (
            "\n".join(_record_line(name, payload) for name, payload in members.items())
            + f"\n{record_name},,\n"
        )
    members[record_name] = record.encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_relax_replaces_the_stale_cryptography_upper_bound() -> None:
    """The official 1.5.3 Requires-Dist line is rewritten in place."""

    metadata = "Requires-Dist: cryptography<49,>=48.0.1\n"

    assert (
        rewrite.relax_cryptography_requires_dist(metadata)
        == "Requires-Dist: cryptography>=48.0.1\n"
    )


def test_relax_is_idempotent_when_the_bound_is_already_open() -> None:
    """A previously patched METADATA file is left unchanged."""

    metadata = "Requires-Dist: cryptography>=48.0.1\n"

    assert rewrite.relax_cryptography_requires_dist(metadata) == metadata


def test_relax_rejects_metadata_without_the_expected_bound() -> None:
    """Unknown cryptography metadata is not silently accepted."""

    with pytest.raises(ValueError, match="does not declare the expected"):
        rewrite.relax_cryptography_requires_dist("Requires-Dist: requests\n")


def test_update_record_entry_rewrites_only_the_named_member() -> None:
    """RECORD keeps sibling lines and updates digest plus size."""

    payload = b"hello"
    record = "keep,sha256=old,1\ndemo-1.0.dist-info/METADATA,sha256=old,1\n"

    updated = rewrite.update_record_entry(record, "demo-1.0.dist-info/METADATA", payload)

    assert updated.startswith("keep,sha256=old,1\n")
    assert "demo-1.0.dist-info/METADATA," + rewrite.record_digest(payload) in updated
    assert updated.endswith("\n")


def test_update_record_entry_rejects_a_missing_member() -> None:
    """A wheel whose RECORD omits METADATA cannot be trusted."""

    with pytest.raises(ValueError, match="does not list"):
        rewrite.update_record_entry("other,sha256=old,1\n", "missing", b"x")


def test_zip_name_is_unsafe_rejects_escape_and_empty_paths() -> None:
    """Traversal, absolute, NUL, and empty zip names fail closed."""

    assert rewrite.zip_name_is_unsafe("")
    assert rewrite.zip_name_is_unsafe("/abs")
    assert rewrite.zip_name_is_unsafe("a\x00b")
    assert rewrite.zip_name_is_unsafe("../evil")
    assert rewrite.zip_name_is_unsafe("foo/../bar")
    assert rewrite.zip_name_is_unsafe("foo//bar")
    assert not rewrite.zip_name_is_unsafe("demo-1.0.dist-info/METADATA")


def test_patch_wheel_rewrites_metadata_and_record(tmp_path: Path) -> None:
    """The patched wheel keeps sibling members and a matching RECORD digest."""

    source = tmp_path / "official.whl"
    destination = tmp_path / "patched.whl"
    _write_wheel(source, "Requires-Dist: cryptography<49,>=48.0.1\n")

    digest = rewrite.patch_wheel(source, destination)

    assert digest == rewrite.sha256_hex(destination.read_bytes())
    with zipfile.ZipFile(destination) as archive:
        metadata = archive.read("demo-1.0.dist-info/METADATA").decode("utf-8")
        record = archive.read("demo-1.0.dist-info/RECORD").decode("utf-8")
        assert "cryptography>=48.0.1" in metadata
        assert "cryptography<49" not in metadata
        assert archive.read("demo/__init__.py") == b""
    assert "demo-1.0.dist-info/METADATA," in record


def test_patch_wheel_rejects_non_regular_input(tmp_path: Path) -> None:
    """Symlinks and missing files cannot be used as the official wheel."""

    missing = tmp_path / "missing.whl"
    link = tmp_path / "link.whl"
    target = tmp_path / "target.whl"
    target.write_bytes(b"x")
    link.symlink_to(target)

    with pytest.raises(ValueError, match="regular file"):
        rewrite.patch_wheel(missing, tmp_path / "out.whl")
    with pytest.raises(ValueError, match="regular file"):
        rewrite.patch_wheel(link, tmp_path / "out.whl")


def test_patch_wheel_rejects_unsafe_members(tmp_path: Path) -> None:
    """A zip slip member aborts before any patched output is trusted."""

    source = tmp_path / "unsafe.whl"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../evil", b"no")
        archive.writestr("demo-1.0.dist-info/METADATA", b"Requires-Dist: cryptography<49,>=48.0.1\n")
        archive.writestr("demo-1.0.dist-info/RECORD", b"x")

    with pytest.raises(ValueError, match="unsafe wheel member"):
        rewrite.patch_wheel(source, tmp_path / "out.whl")


def test_patch_wheel_rejects_missing_metadata_or_record(tmp_path: Path) -> None:
    """Both METADATA and RECORD are required before a patched wheel is written."""

    source = tmp_path / "incomplete.whl"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("demo-1.0.dist-info/METADATA", b"Requires-Dist: cryptography<49,>=48.0.1\n")

    with pytest.raises(ValueError, match="missing METADATA or RECORD"):
        rewrite.patch_wheel(source, tmp_path / "out.whl")


def test_rewrite_lock_find_links_replaces_existing_directives() -> None:
    """Header comments stay; previous find-links lines are replaced."""

    lock = "# header\n--find-links old\n\npkg==1.0 \\\n    --hash=sha256:" + ("a" * 64) + "\n"

    updated = rewrite.rewrite_lock_find_links(lock, ["vendor/strix", "https://example.test/wheel.whl"])

    assert updated.startswith("# header\n--find-links vendor/strix\n")
    assert "--find-links old" not in updated
    assert "pkg==1.0" in updated


def test_rewrite_lock_find_links_comment_only_lock() -> None:
    """A comment-only lock still receives find-links after the header."""

    updated = rewrite.rewrite_lock_find_links("# only\n# header\n", ["vendor/strix"])

    assert updated == "# only\n# header\n--find-links vendor/strix\n\n"


def test_rewrite_lock_find_links_without_header_comments() -> None:
    """A headerless lock still receives find-links before the first pin."""

    updated = rewrite.rewrite_lock_find_links("pkg==1.0\n", ["vendor/strix"])

    assert updated.startswith("--find-links vendor/strix\n\npkg==1.0\n")


def test_update_record_entry_preserves_a_missing_trailing_newline() -> None:
    """RECORD files that omit a final newline stay in that shape."""

    payload = b"x"
    updated = rewrite.update_record_entry(
        "demo-1.0.dist-info/METADATA,sha256=old,1",
        "demo-1.0.dist-info/METADATA",
        payload,
    )

    assert not updated.endswith("\n")
    assert rewrite.record_digest(payload) in updated


def test_rewrite_lock_find_links_requires_at_least_one_location() -> None:
    """A lock rewrite without find-links would hide the patched wheel."""

    with pytest.raises(ValueError, match="at least one --find-links"):
        rewrite.rewrite_lock_find_links("# header\n", [])


def test_rewrite_lock_strix_agent_hashes_keeps_the_1_5_3_pin() -> None:
    """The lock still names 1.5.3 and carries only the patched digest."""

    official = "b" * 64
    patched = "c" * 64
    wheel_url = "vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl"
    lock = (
        f"strix-agent==1.5.3 \\\n    --hash=sha256:{official} \\\n"
        f"    --hash=sha256:{'d' * 64}\n    # via -r requirements-strix-ci.txt\n"
    )

    updated = rewrite.rewrite_lock_strix_agent_hashes(lock, patched, wheel_url)

    assert f"strix-agent @ {wheel_url} \\" in updated
    assert patched in updated
    assert official not in updated
    assert "d" * 64 not in updated


def test_rewrite_lock_strix_agent_hashes_rejects_bad_digest_and_missing_block() -> None:
    """Lock surgery fails closed on a malformed digest, URL, or missing pin."""

    wheel_url = "vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl"
    with pytest.raises(ValueError, match="64-character"):
        rewrite.rewrite_lock_strix_agent_hashes("strix-agent==1.5.3\n", "abc", wheel_url)
    with pytest.raises(ValueError, match="without traversal"):
        rewrite.rewrite_lock_strix_agent_hashes(
            "strix-agent==1.5.3\n", "a" * 64, "vendor/strix/foo bar.whl"
        )
    with pytest.raises(ValueError, match="without traversal"):
        rewrite.rewrite_lock_strix_agent_hashes("strix-agent==1.5.3\n", "a" * 64, "vendor/strix/../evil.whl")
    with pytest.raises(ValueError, match="published GitHub raw path or vendor/strix"):
        rewrite.rewrite_lock_strix_agent_hashes("strix-agent==1.5.3\n", "a" * 64, "https://example.test/wheel.whl")
    with pytest.raises(ValueError, match="1.5.3 manylinux"):
        rewrite.rewrite_lock_strix_agent_hashes("strix-agent==1.5.3\n", "a" * 64, "vendor/strix/other.whl")
    with pytest.raises(ValueError, match="exactly one strix-agent"):
        rewrite.rewrite_lock_strix_agent_hashes("pkg==1.0\n", "a" * 64, wheel_url)


def test_main_patches_a_wheel_without_rewriting_a_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI prints the patched digest when no lock path is supplied."""

    source = tmp_path / "official.whl"
    destination = tmp_path / "patched.whl"
    _write_wheel(source, "Requires-Dist: cryptography<49,>=48.0.1\n")

    assert rewrite.main(["--input", str(source), "--output", str(destination)]) == 0
    assert capsys.readouterr().out.strip() == rewrite.sha256_hex(destination.read_bytes())


def test_main_rewrites_the_lock_and_reports_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Lock rewriting requires find-links and a regular lock file."""

    source = tmp_path / "official.whl"
    destination = tmp_path / "patched.whl"
    lock = tmp_path / "requirements-strix-ci-hashes.txt"
    _write_wheel(source, "Requires-Dist: cryptography<49,>=48.0.1\n")
    lock.write_text(
        "# header\nstrix-agent==1.5.3 \\\n    --hash=sha256:" + ("e" * 64) + "\n",
        encoding="utf-8",
    )

    assert (
        rewrite.main(
            [
                "--input",
                str(source),
                "--output",
                str(destination),
                "--lock",
                str(lock),
            ]
        )
        == 1
    )
    assert "requires --wheel-url" in capsys.readouterr().err

    missing_lock = tmp_path / "missing.txt"
    assert (
        rewrite.main(
            [
                "--input",
                str(source),
                "--output",
                str(destination),
                "--lock",
                str(missing_lock),
                "--wheel-url",
                "vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl",
            ]
        )
        == 1
    )

    link = tmp_path / "lock-link.txt"
    link.symlink_to(lock)
    assert (
        rewrite.main(
            [
                "--input",
                str(source),
                "--output",
                str(destination),
                "--lock",
                str(link),
                "--wheel-url",
                "vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl",
            ]
        )
        == 1
    )

    assert (
        rewrite.main(
            [
                "--input",
                str(source),
                "--output",
                str(destination),
                "--lock",
                str(lock),
                "--wheel-url",
                "vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl",
                "--find-links",
                "vendor/strix",
            ]
        )
        == 0
    )
    text = lock.read_text(encoding="utf-8")
    assert "--find-links vendor/strix" in text
    assert "strix-agent @ vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl" in text
    assert rewrite.sha256_hex(destination.read_bytes()) in text

    lock.write_text(
        "# header\nstrix-agent==1.5.3 \\\n    --hash=sha256:" + ("e" * 64) + "\n",
        encoding="utf-8",
    )
    assert (
        rewrite.main(
            [
                "--input",
                str(source),
                "--output",
                str(destination),
                "--lock",
                str(lock),
                "--wheel-url",
                "vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl",
            ]
        )
        == 0
    )
    assert "--find-links" not in lock.read_text(encoding="utf-8")


def test_main_reports_a_bad_zip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Corrupt official input is reported instead of producing a wheel."""

    source = tmp_path / "not-a-zip.whl"
    source.write_bytes(b"not-a-zip")

    assert rewrite.main(["--input", str(source), "--output", str(tmp_path / "out.whl")]) == 1
    assert "ERROR:" in capsys.readouterr().err


def test_script_entrypoint_exits_with_main_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module entrypoint delegates to main and preserves the status code."""

    source = tmp_path / "official.whl"
    destination = tmp_path / "patched.whl"
    _write_wheel(source, "Requires-Dist: cryptography>=48.0.1\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rewrite_strix_agent_cryptography_bound.py",
            "--input",
            str(source),
            "--output",
            str(destination),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(Path("scripts/ci/rewrite_strix_agent_cryptography_bound.py")),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert destination.is_file()


def test_vendored_wheel_and_lock_stay_resolver_compatible() -> None:
    """The committed wheel and lock are the buyer-visible 1.5.3 + crypto 50 pair."""

    assert VENDOR_WHEEL.is_file()
    assert not VENDOR_WHEEL.is_symlink()
    digest = rewrite.sha256_hex(VENDOR_WHEEL.read_bytes())
    lock = LOCK.read_text(encoding="utf-8")
    assert f"--hash=sha256:{digest}" in lock
    assert "strix-agent @ https://raw.githubusercontent.com/ContextualWisdomLab/.github/" in lock
    assert "--find-links" not in lock
    assert PUBLISHED_REF.read_text(encoding="utf-8").strip()
    source = SOURCE.read_text(encoding="utf-8")
    assert "ba0b6b13f13f41e45f3eb4dba515641d1bc71363ca6e758d0cd05c20ff56b6ea" in source
    assert "Apache-2.0" in source
    with zipfile.ZipFile(VENDOR_WHEEL) as archive:
        metadata = archive.read("strix_agent-1.5.3.dist-info/METADATA").decode("utf-8")
    assert "cryptography>=48.0.1" in metadata
    assert "cryptography<49" not in metadata


def test_compile_and_quality_rerun_when_the_rewriter_changes() -> None:
    """Regeneration and quality CI must see the rewriter and vendored wheel."""

    script = COMPILE.read_text(encoding="utf-8")
    trigger = QUALITY.read_text(encoding="utf-8")
    assert "rewrite_strix_agent_cryptography_bound.py" in script
    assert "vendor/strix" in script
    assert "scripts/ci/rewrite_strix_agent_cryptography_bound.py" in trigger
    assert "tests/test_rewrite_strix_agent_cryptography_bound.py" in trigger
    assert "vendor/strix/" in trigger
