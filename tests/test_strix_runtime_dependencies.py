from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


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


def test_every_exact_strix_requirement_is_present_in_the_hash_lock() -> None:
    """A successful --no-deps install must not hide a missing direct package."""
    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    direct_exact = re.findall(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;]+)",
        requirements,
        re.MULTILINE,
    )
    missing = [
        f"{name}=={version}"
        for name, version in direct_exact
        if not re.search(
            rf"(?m)^{re.escape(name)}=={re.escape(version)}\s+\\$",
            requirements_lock,
        )
    ]
    assert not missing, f"direct Strix requirements missing from hash lock: {missing}"
