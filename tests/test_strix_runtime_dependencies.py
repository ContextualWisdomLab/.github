from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _locked_requirement_versions(
    requirements_text: str, package_name: str
) -> list[str]:
    """Return every exact version row for one normalized package name."""
    package_versions = []
    for requirement_line in requirements_text.splitlines():
        requirement_name, separator, version_and_hash_marker = (
            requirement_line.strip().partition("==")
        )
        requirement_name = requirement_name.split("[", 1)[0].strip()
        if separator and requirement_name.casefold() == package_name.casefold():
            package_versions.append(version_and_hash_marker.split()[0])
    return package_versions


def test_locked_requirement_versions_normalizes_extras() -> None:
    """Treat extras as the same distribution when detecting duplicate pins."""
    requirements = "pyjwt==2.14.0\npyjwt[crypto]==2.13.0\n"

    assert _locked_requirement_versions(requirements, "pyjwt") == [
        "2.14.0",
        "2.13.0",
    ]


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


def test_strix_pyjwt_security_pin_is_an_explicit_lock_input() -> None:
    """Keep PyJWT above the GHSA-42vr-xj54-vc7v parser DoS fix."""
    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    assert _locked_requirement_versions(requirements, "pyjwt") == ["2.15.1"]
    assert _locked_requirement_versions(requirements_lock, "pyjwt") == ["2.15.1"]


def test_strix_litellm_security_pin_is_an_explicit_lock_input() -> None:
    """Keep the patched LiteLLM credential boundary reproducible."""
    requirements = (REPOSITORY_ROOT / "requirements-strix-ci.txt").read_text(
        encoding="utf-8"
    )
    requirements_lock = (
        REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    assert _locked_requirement_versions(requirements, "litellm") == ["1.94.3"]
    assert _locked_requirement_versions(requirements_lock, "litellm") == ["1.94.3"]


def test_python_security_inputs_pin_patched_urllib3() -> None:
    """Keep both audited runtimes on the urllib3 security release."""
    requirement_pairs = (
        ("requirements-pip-audit-ci.txt", "requirements-pip-audit-ci-hashes.txt"),
        ("requirements-strix-ci.txt", "requirements-strix-ci-hashes.txt"),
    )

    for source_name, lock_name in requirement_pairs:
        source_text = (REPOSITORY_ROOT / source_name).read_text(encoding="utf-8")
        lock_text = (REPOSITORY_ROOT / lock_name).read_text(encoding="utf-8")

        assert _locked_requirement_versions(source_text, "urllib3") == ["2.8.0"]
        assert _locked_requirement_versions(lock_text, "urllib3") == ["2.8.0"]
