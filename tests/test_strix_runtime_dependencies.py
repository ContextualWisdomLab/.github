from pathlib import Path


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


def test_strix_anyio_security_pin_is_an_explicit_lock_input() -> None:
    """Keep the audited AnyIO version reproducible from the source input."""
    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    assert "anyio==4.14.2" in requirements.splitlines()
    assert "anyio==4.14.2 \\" in requirements_lock.splitlines()
