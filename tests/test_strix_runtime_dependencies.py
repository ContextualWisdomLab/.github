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


def test_strix_jwt_and_http_security_pins_are_explicit_lock_inputs() -> None:
    """Keep the audited PyJWT and urllib3 versions reproducible from source."""

    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    for requirement in ("pyjwt==2.15.0", "urllib3==2.8.0"):
        assert requirement in requirements.splitlines()
        assert f"{requirement} \\" in requirements_lock.splitlines()


def test_pip_audit_http_security_pin_is_an_explicit_lock_input() -> None:
    """Keep pip-audit's audited urllib3 version reproducible from source."""

    requirements = (
        REPOSITORY_ROOT / "requirements-pip-audit-ci.txt"
    ).read_text(encoding="utf-8")
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-pip-audit-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    assert "urllib3==2.8.0" in requirements.splitlines()
    assert "urllib3==2.8.0 \\" in requirements_lock.splitlines()
