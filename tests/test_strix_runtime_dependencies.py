from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_EXACT_REQUIREMENT_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9._,-]+\])?==([^\s;]+)",
    re.MULTILINE,
)


def _direct_exact_requirements(requirements: str) -> list[tuple[str, str]]:
    """Return base package names and exact versions, preserving extras semantics."""
    return _EXACT_REQUIREMENT_RE.findall(requirements)


def _hash_lock_has_exact_pin(requirements_lock: str, name: str, version: str) -> bool:
    """Accept an exact pin whether hashes continue on this line or the next."""
    return bool(
        re.search(
            rf"(?m)^{re.escape(name)}=={re.escape(version)}(?=\s|$)",
            requirements_lock,
        )
    )


def test_strix_installs_openai_httpx2_runtime() -> None:
    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    assert "openai[httpx2]==2.54.0" in requirements.splitlines()
    assert "openai==2.54.0 \\" in requirements_lock.splitlines()
    assert "httpx2==2.12.0 \\" in requirements_lock.splitlines()


def test_exact_requirement_parser_keeps_base_name_for_extras() -> None:
    assert _direct_exact_requirements("openai[httpx2]==2.54.0\n") == [
        ("openai", "2.54.0")
    ]


def test_hash_lock_pin_accepts_multiline_and_single_line_hash_forms() -> None:
    multiline = "openai==2.54.0 \\\n    --hash=sha256:abc\n"
    single_line = "openai==2.54.0 --hash=sha256:abc\n"

    assert _hash_lock_has_exact_pin(multiline, "openai", "2.54.0")
    assert _hash_lock_has_exact_pin(single_line, "openai", "2.54.0")
    assert not _hash_lock_has_exact_pin(single_line, "openai", "2.54.1")


def test_every_exact_strix_requirement_is_present_in_the_hash_lock() -> None:
    """A successful --no-deps install must not hide a missing direct package."""
    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    direct_exact = _direct_exact_requirements(requirements)
    missing = [
        f"{name}=={version}"
        for name, version in direct_exact
        if not _hash_lock_has_exact_pin(requirements_lock, name, version)
    ]
    assert not missing, f"direct Strix requirements missing from hash lock: {missing}"
