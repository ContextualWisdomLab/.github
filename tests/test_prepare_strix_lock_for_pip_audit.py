"""Tests for pip-audit normalization of the Strix URL-pinned lock."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import prepare_strix_lock_for_pip_audit as prepare


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
SECURITY = ROOT / ".github" / "workflows" / "python-security.yml"
QUALITY = ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"


def test_version_from_wheel_url_reads_the_pep_427_filename() -> None:
    """The 1.5.3 manylinux wheel name is the version source of truth."""

    assert (
        prepare.version_from_wheel_url(
            "https://example.test/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl"
        )
        == "1.5.3"
    )


def test_version_from_wheel_url_rejects_traversal_and_unversioned_names() -> None:
    """A URL that cannot name an exact wheel version fails closed."""

    with pytest.raises(ValueError, match="without traversal"):
        prepare.version_from_wheel_url("vendor/strix/../evil.whl")
    with pytest.raises(ValueError, match="without traversal"):
        prepare.version_from_wheel_url("vendor/strix/foo bar.whl")
    with pytest.raises(ValueError, match="without traversal"):
        prepare.version_from_wheel_url("vendor/strix/foo\nbar.whl")
    with pytest.raises(ValueError, match="does not encode a package version"):
        prepare.version_from_wheel_url("https://example.test/strix-agent.tar.gz")


def test_normalize_rewrites_only_the_url_pin() -> None:
    """Hash lines and ordinary == pins stay byte-identical besides the URL line."""

    lock = (
        "# header\n"
        "cryptography==50.0.0 \\\n"
        "    --hash=sha256:" + ("a" * 64) + "\n"
        "strix-agent @ vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl \\\n"
        "    --hash=sha256:" + ("b" * 64) + "\n"
    )

    normalized = prepare.normalize_lock_for_disable_pip(lock)

    assert "strix-agent==1.5.3 \\" in normalized
    assert "strix-agent @" not in normalized
    assert "cryptography==50.0.0 \\" in normalized
    assert "b" * 64 in normalized


def test_normalize_accepts_a_single_line_url_requirement() -> None:
    """A URL pin without a continuation marker still becomes name==version."""

    lock = "strix-agent @ vendor/strix/strix_agent-1.5.3-py3-none-any.whl\n"

    assert prepare.normalize_lock_for_disable_pip(lock) == "strix-agent==1.5.3\n"


def test_normalize_preserves_a_missing_trailing_newline() -> None:
    """Locks that omit a final newline stay in that shape."""

    lock = "pkg==1.0"

    assert prepare.normalize_lock_for_disable_pip(lock) == "pkg==1.0"


def test_main_writes_a_disable_pip_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI copies hashes and fails closed on unsafe or missing input."""

    source = tmp_path / "requirements-strix-ci-hashes.txt"
    destination = tmp_path / "prepared.txt"
    source.write_text(
        "strix-agent @ vendor/strix/strix_agent-1.5.3-py3-none-manylinux_2_17_x86_64.whl \\\n"
        "    --hash=sha256:" + ("c" * 64) + "\n",
        encoding="utf-8",
    )

    assert prepare.main(["--input", str(source), "--output", str(destination)]) == 0
    assert "strix-agent==1.5.3 \\" in destination.read_text(encoding="utf-8")

    missing = tmp_path / "missing.txt"
    assert prepare.main(["--input", str(missing), "--output", str(destination)]) == 1
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    assert prepare.main(["--input", str(link), "--output", str(destination)]) == 1
    broken = tmp_path / "broken.txt"
    broken.write_text("strix-agent @ https://example.test/not-a-wheel\n", encoding="utf-8")
    assert prepare.main(["--input", str(broken), "--output", str(destination)]) == 1
    leftover = tmp_path / "leftover.txt"
    leftover.write_text("requests==2.0.0\n", encoding="utf-8")
    assert prepare.main(["--input", str(leftover), "--output", str(destination)]) == 1
    assert "ERROR:" in capsys.readouterr().err


def test_main_rejects_a_lock_that_keeps_a_url_requirement(tmp_path: Path) -> None:
    """A normalize miss that leaves ``name @ url`` cannot be audited."""

    source = tmp_path / "requirements-strix-ci-hashes.txt"
    source.write_text(
        "strix-agent==1.5.3\nstrix-agent @ vendor/strix/strix_agent-1.5.3-py3-none-any.whl\n",
        encoding="utf-8",
    )

    def fake_normalize(lock_text: str) -> str:
        """Return the URL pin unchanged so the post-condition can fail."""

        return lock_text

    original = prepare.normalize_lock_for_disable_pip
    prepare.normalize_lock_for_disable_pip = fake_normalize
    try:
        assert prepare.main(["--input", str(source), "--output", str(tmp_path / "out.txt")]) == 1
    finally:
        prepare.normalize_lock_for_disable_pip = original


def test_script_entrypoint_exits_with_main_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module entrypoint delegates to main and preserves the status code."""

    source = tmp_path / "requirements-strix-ci-hashes.txt"
    destination = tmp_path / "prepared.txt"
    source.write_text(
        "strix-agent @ vendor/strix/strix_agent-1.5.3-py3-none-any.whl\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_strix_lock_for_pip_audit.py",
            "--input",
            str(source),
            "--output",
            str(destination),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            str(Path("scripts/ci/prepare_strix_lock_for_pip_audit.py")),
            run_name="__main__",
        )

    assert exc_info.value.code == 0
    assert destination.read_text(encoding="utf-8") == "strix-agent==1.5.3\n"


def test_committed_lock_normalizes_to_strix_agent_1_5_3() -> None:
    """The published URL lock must become a disable-pip name==version pin."""

    normalized = prepare.normalize_lock_for_disable_pip(LOCK.read_text(encoding="utf-8"))
    assert "strix-agent==1.5.3 \\" in normalized
    assert "strix-agent @" not in normalized
    assert "cryptography==50.0.0" in normalized


def test_python_security_skips_the_unhashed_compile_input() -> None:
    """pip-audit must not re-resolve requirements-strix-ci.txt."""

    security = SECURITY.read_text(encoding="utf-8")
    assert "prepare_strix_lock_for_pip_audit.py" in security
    assert "requirements-strix-ci.txt" in security
    assert "Skipping unhashed Strix compile input" in security
    assert "pip-audit --strict --desc=on --disable-pip -r" in security
    trigger = QUALITY.read_text(encoding="utf-8")
    assert "scripts/ci/prepare_strix_lock_for_pip_audit.py" in trigger
    assert "tests/test_prepare_strix_lock_for_pip_audit.py" in trigger
