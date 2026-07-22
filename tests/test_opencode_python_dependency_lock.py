"""Contracts for application dependencies trusted by offline OpenCode coverage."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TRUSTED_SAJU_WHEELS = {
    "bcrypt": "5.0.0",
    "fastapi": "0.139.2",
    "httpx": "0.28.1",
    "icalendar": "7.2.0",
    "korean-lunar-calendar": "0.4.0",
}


def _top_level_requirement(line: str) -> str | None:
    """Return a requirement token from one non-indented, non-comment line."""

    if not line or line[0].isspace() or line.startswith("#"):
        return None
    header = line.split("\\", 1)[0].strip()
    if not header or header.startswith("-"):
        return None
    return header.split(maxsplit=1)[0]


def _top_level_requirements(text: str) -> set[str]:
    """Return parsed top-level requirements without comments or stanza details."""

    return {
        requirement
        for line in text.splitlines()
        if (requirement := _top_level_requirement(line)) is not None
    }


def _lock_stanza(lock: str, requirement: str) -> list[str]:
    """Return one top-level requirement stanza without borrowing later hashes."""

    lines = lock.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if _top_level_requirement(line) == requirement
        ),
        None,
    )
    assert start is not None, f"{requirement} is missing from the hashed dependency lock"

    stanza = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        if not line[0].isspace() and not line.startswith("#"):
            break
        stanza.append(line)
    return stanza


def test_lock_stanza_accepts_indented_via_comments() -> None:
    lock = (
        "demo==1.0 \\\n"
        "    --hash=sha256:abc123\n"
        "    # via example\n"
        "next-package==2.0 \\\n"
        "    --hash=sha256:def456\n"
    )

    assert _lock_stanza(lock, "demo==1.0") == [
        "demo==1.0 \\",
        "    --hash=sha256:abc123",
        "    # via example",
    ]


def test_lock_stanza_accepts_attached_line_continuation() -> None:
    lock = "demo==1.0\\\n    --hash=sha256:abc123\n"

    assert _lock_stanza(lock, "demo==1.0") == [
        "demo==1.0\\",
        "    --hash=sha256:abc123",
    ]


def test_lock_stanza_does_not_borrow_a_later_requirement_hash() -> None:
    lock = (
        "demo==1.0\n"
        "next-package==2.0 \\\n"
        "    --hash=sha256:def456\n"
    )

    assert not any(
        line.lstrip().startswith("--hash=sha256:")
        for line in _lock_stanza(lock, "demo==1.0")
    )


def test_top_level_requirements_ignore_comments_and_stanza_details() -> None:
    requirements = _top_level_requirements(
        "# lunar-python==9.9.9 is intentionally not installed\n"
        "demo==1.0 \\\n"
        "    --hash=sha256:abc123\n"
        "    # via lunar-python==9.9.9\n"
    )

    assert requirements == {"demo==1.0"}


def test_saju_caldav_dependencies_are_exact_hash_locked_wheels() -> None:
    source = (REPO_ROOT / "requirements-opencode-review-ci.txt").read_text(
        encoding="utf-8"
    )
    lock = (REPO_ROOT / "requirements-opencode-review-ci-hashes.txt").read_text(
        encoding="utf-8"
    )
    source_requirements = _top_level_requirements(source)
    lock_requirements = _top_level_requirements(lock)

    for package, version in TRUSTED_SAJU_WHEELS.items():
        requirement = f"{package}=={version}"
        assert requirement in source_requirements
        stanza = _lock_stanza(lock, requirement)
        assert any(
            line.lstrip().startswith("--hash=sha256:") for line in stanza[1:]
        ), f"{requirement} has no artifact hash in its lock stanza"

    assert not any(
        requirement.startswith("lunar-python==")
        for requirement in source_requirements | lock_requirements
    )

    generation_header = "\n".join(
        line for line in lock.splitlines() if line.startswith("#")
    )
    for fragment in (
        "uv pip compile",
        "--generate-hashes",
        "--python-version 3.12",
        "--python-platform x86_64-manylinux_2_28",
        "requirements-opencode-review-ci.txt",
        "requirements-opencode-review-ci-hashes.txt",
    ):
        assert fragment in generation_header
