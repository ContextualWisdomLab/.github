"""Contracts for application dependencies trusted by offline OpenCode coverage."""

from pathlib import Path


TRUSTED_SAJU_WHEELS = {
    "bcrypt": "5.0.0",
    "fastapi": "0.139.2",
    "httpx": "0.28.1",
    "icalendar": "7.2.0",
    "korean-lunar-calendar": "0.4.0",
}


def test_saju_caldav_dependencies_are_exact_hash_locked_wheels() -> None:
    source = Path("requirements-opencode-review-ci.txt").read_text(encoding="utf-8")
    lock = Path("requirements-opencode-review-ci-hashes.txt").read_text(encoding="utf-8")

    for package, version in TRUSTED_SAJU_WHEELS.items():
        requirement = f"{package}=={version}"
        assert requirement in source
        locked_requirement = lock.split(requirement, 1)[1].split("\n", 1)[0]
        assert locked_requirement.rstrip().endswith("\\")
        assert "--hash=sha256:" in lock.split(requirement, 1)[1].split("\n# via", 1)[0]

    assert "lunar-python==" not in source
    assert "lunar-python==" not in lock
    assert (
        "uv pip compile --generate-hashes --python-version 3.12 "
        "--python-platform x86_64-manylinux_2_28 requirements-opencode-review-ci.txt "
        "-o requirements-opencode-review-ci-hashes.txt"
    ) in lock
