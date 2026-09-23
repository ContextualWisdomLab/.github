"""Install and capture must resolve from the same validated sources (#2342).

``pip install -r <lock>`` reads the real lock and honors ``--index-url``,
``--extra-index-url`` and ``--find-links`` in it. The capture step's
``pip download`` used a reconstructed plain requirements file built with
``grep -oE '^[A-Za-z0-9._-]+==[^ ;]+'``, which drops every ``-``-prefixed
directive. Collection could therefore resolve from a different source than
install, and any lock using a private or extra index failed capture outright.

The fix never forwards what the lock says. Every directive is parsed, validated
against the same trusted-origin and bounded-path policy
``materialize_base_python_requirements.py`` applies, and only then emitted as an
explicit option list. These tests cover both directions: the supported forms that
must now reach ``pip download``, and every unsupported or untrusted form, which
must fail explicitly rather than be dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materialize
from scripts.ci import release_dependency_gate as gate

_PIN = "greenlib==1.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"


def _options(text: str, root: Path) -> list[str]:
    """Validate one lock's directives and return the pip options they produce."""
    return gate.lock_download_options(text, root)


# ---------------------------------------------------------------------------
# Positive: the supported forms reach pip download
# ---------------------------------------------------------------------------


def test_a_lock_with_no_directives_produces_no_options(tmp_path: Path) -> None:
    """This organization's own hash-pinned locks use no source directives."""
    assert _options(_PIN, tmp_path) == []


def test_an_allowlisted_index_url_is_forwarded(tmp_path: Path) -> None:
    """A trusted HTTPS index origin is passed through so download matches install."""
    text = f"--index-url https://pypi.org/simple\n{_PIN}"
    assert _options(text, tmp_path) == ["--index-url", "https://pypi.org/simple"]


def test_an_allowlisted_extra_index_url_is_forwarded(tmp_path: Path) -> None:
    """`--extra-index-url` is honored on the same terms as `--index-url`."""
    text = f"--extra-index-url https://files.pythonhosted.org/simple\n{_PIN}"
    assert _options(text, tmp_path) == [
        "--extra-index-url",
        "https://files.pythonhosted.org/simple",
    ]


def test_the_equals_spelling_is_accepted(tmp_path: Path) -> None:
    """pip accepts `--opt=value`, so the validator must read it identically."""
    text = f"--index-url=https://pypi.org/simple\n{_PIN}"
    assert _options(text, tmp_path) == ["--index-url", "https://pypi.org/simple"]


def test_the_short_index_spelling_is_accepted(tmp_path: Path) -> None:
    """`-i` is pip's short form of `--index-url` and must not be dropped."""
    text = f"-i https://pypi.org/simple\n{_PIN}"
    assert _options(text, tmp_path) == ["-i", "https://pypi.org/simple"]


def test_an_allowed_offline_find_links_root_resolves_to_an_absolute_path(
    tmp_path: Path,
) -> None:
    """A permitted offline wheel directory collects, resolved inside the release tree."""
    (tmp_path / "wheels").mkdir()
    text = f"--find-links wheels\n{_PIN}"
    options = _options(text, tmp_path)
    assert options[0] == "--find-links"
    assert Path(options[1]) == (tmp_path / "wheels").resolve()
    assert Path(options[1]).is_absolute()


def test_a_nested_find_links_directory_is_allowed(tmp_path: Path) -> None:
    """A deeper permitted path inside the release tree is still bounded."""
    (tmp_path / "fixtures" / "wheels").mkdir(parents=True)
    options = _options(f"--find-links fixtures/wheels\n{_PIN}", tmp_path)
    assert Path(options[1]) == (tmp_path / "fixtures" / "wheels").resolve()


def test_the_short_find_links_spelling_is_accepted(tmp_path: Path) -> None:
    """`-f` is pip's short form of `--find-links`."""
    (tmp_path / "wheels").mkdir()
    options = _options(f"-f wheels\n{_PIN}", tmp_path)
    assert options[0] == "-f"


def test_several_directives_are_forwarded_in_lock_order(tmp_path: Path) -> None:
    """Order matters to pip's resolution, so it is preserved exactly."""
    (tmp_path / "wheels").mkdir()
    text = (
        "--index-url https://pypi.org/simple\n"
        "--extra-index-url https://files.pythonhosted.org/simple\n"
        f"--find-links wheels\n{_PIN}"
    )
    options = _options(text, tmp_path)
    assert options[:4] == [
        "--index-url",
        "https://pypi.org/simple",
        "--extra-index-url",
        "https://files.pythonhosted.org/simple",
    ]
    assert options[4] == "--find-links"


def test_comments_and_hash_continuations_are_not_directives(tmp_path: Path) -> None:
    """A `--hash=` continuation and a comment are not source directives."""
    text = f"# --index-url https://evil.invalid/simple\n{_PIN}"
    assert _options(text, tmp_path) == []


# ---------------------------------------------------------------------------
# Negative: untrusted origins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://packages.evil.invalid/simple",
        "https://pypi.org.evil.invalid/simple",
        "https://internal-mirror.corp.invalid/simple",
    ],
)
def test_an_external_origin_not_on_the_allowlist_fails_explicitly(
    tmp_path: Path, url: str
) -> None:
    """An unlisted index host is refused; it is never quietly dropped."""
    with pytest.raises(gate.GateError) as error:
        _options(f"--index-url {url}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_ORIGIN_DENIED


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/simple",
        "file:///etc/wheels",
        "ftp://pypi.org/simple",
        "https://pypi.org:8443/simple",
    ],
)
def test_a_non_allowed_scheme_or_port_fails_explicitly(tmp_path: Path, url: str) -> None:
    """Only HTTPS on the default port is an acceptable index origin."""
    with pytest.raises(gate.GateError) as error:
        _options(f"--index-url {url}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_ORIGIN_DENIED


def test_a_malformed_port_fails_rather_than_raising_value_error(tmp_path: Path) -> None:
    """An unparseable port is refused, not allowed to escape as a ValueError."""
    with pytest.raises(gate.GateError) as error:
        _options(f"--index-url https://pypi.org:notaport/simple\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_ORIGIN_DENIED


# ---------------------------------------------------------------------------
# Negative: credentials in a URL, with no material in the reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://buildbot:s3cr3t-T0KEN@pypi.org/simple",
        "https://s3cr3t-T0KEN@pypi.org/simple",
        "https://buildbot:s3cr3t-T0KEN@packages.evil.invalid/simple",
    ],
)
def test_a_url_carrying_userinfo_fails_and_leaks_no_credential(
    tmp_path: Path, url: str
) -> None:
    """Userinfo is a negative case, and the refusal carries no credential material."""
    with pytest.raises(gate.GateError) as error:
        _options(f"--index-url {url}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_CREDENTIAL_IN_URL
    message = str(error.value)
    for secret in ("s3cr3t-T0KEN", "buildbot"):
        assert secret not in message
    # The whole URL is withheld, so neither the host nor the path can carry a token out.
    assert url not in message
    assert "pypi.org" not in message


def test_userinfo_is_checked_before_the_host_allowlist(tmp_path: Path) -> None:
    """A credential must never be reported as merely an origin problem."""
    with pytest.raises(gate.GateError) as error:
        _options(
            f"--index-url https://user:tok@packages.evil.invalid/simple\n{_PIN}", tmp_path
        )
    assert error.value.code == gate.LOCK_SOURCE_CREDENTIAL_IN_URL
    assert "tok" not in str(error.value)


# ---------------------------------------------------------------------------
# Negative: paths escaping the permitted root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    ["../wheels", "../../etc", "wheels/../../outside", "./wheels", "a/./b"],
)
def test_a_path_escaping_the_permitted_root_fails_explicitly(
    tmp_path: Path, target: str
) -> None:
    """A relative traversal or non-normalized path is refused."""
    with pytest.raises(gate.GateError) as error:
        _options(f"--find-links {target}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_PATH_ESCAPE


@pytest.mark.parametrize(
    "target",
    ["/etc/wheels", "~/wheels", "C:\\wheels", "https://pypi.org/simple", "wheels?x=1"],
)
def test_an_absolute_url_or_unsafe_find_links_target_fails(
    tmp_path: Path, target: str
) -> None:
    """`--find-links` may name only a bounded relative directory, never a URL."""
    with pytest.raises(gate.GateError) as error:
        _options(f"--find-links {target}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_PATH_ESCAPE


def test_a_find_links_target_that_is_not_a_directory_fails(tmp_path: Path) -> None:
    """A missing or non-directory target cannot be an offline wheel source."""
    (tmp_path / "wheels").write_text("not a directory", encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        _options(f"--find-links wheels\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_PATH_ESCAPE


def test_a_symlinked_find_links_target_fails(tmp_path: Path) -> None:
    """A symlink could point outside the release tree after resolution."""
    outside = tmp_path.parent / "outside-wheels"
    outside.mkdir(exist_ok=True)
    (tmp_path / "wheels").symlink_to(outside)
    with pytest.raises(gate.GateError) as error:
        _options(f"--find-links wheels\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_PATH_ESCAPE


def test_the_bounded_path_rules_agree_with_the_existing_include_policy() -> None:
    """The path policy is the repository's existing one, not a second mechanism.

    Every target the established
    ``materialize_base_python_requirements._bounded_requirement_include_target``
    rejects must also be rejected here, so the two cannot drift apart.
    """
    rejected = [
        "../other.txt",
        "/abs/other.txt",
        "~/other.txt",
        "a\\b.txt",
        "a:b.txt",
        "a?b.txt",
        "a#b.txt",
        "./other.txt",
    ]
    for target in rejected:
        assert materialize._bounded_requirement_include_target(f"-r {target}") is None
        with pytest.raises(gate.GateError) as error:
            gate._resolve_bounded_find_links("--find-links", target, Path("/tmp"))
        assert error.value.code == gate.LOCK_SOURCE_PATH_ESCAPE, target


# ---------------------------------------------------------------------------
# Negative: unsupported forms fail rather than being dropped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive",
    ["-r other.txt", "--requirement other.txt", "-c constraints.txt", "--constraint c.txt"],
)
def test_a_nested_include_fails_explicitly(tmp_path: Path, directive: str) -> None:
    """Honoring includes would need a second requirements dialect, so they are refused."""
    with pytest.raises(gate.GateError) as error:
        _options(f"{directive}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_UNSUPPORTED
    assert "inline the closure" in str(error.value)


@pytest.mark.parametrize(
    "directive",
    [
        "--no-index",
        "--trusted-host pypi.org",
        "--pre",
        "--editable .",
        "-e .",
        "--no-binary :all:",
    ],
)
def test_an_unsupported_directive_form_fails_rather_than_being_dropped(
    tmp_path: Path, directive: str
) -> None:
    """Silently dropping a directive is the defect; every unknown form now fails.

    The reason names the form itself. A valueless flag such as `--no-index` must not
    be reported as a value-count problem, which would hide why it is refused.
    """
    with pytest.raises(gate.GateError) as error:
        _options(f"{directive}\n{_PIN}", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_UNSUPPORTED
    assert "is not a supported source form" in str(error.value)


def test_an_environment_marker_fails_explicitly(tmp_path: Path) -> None:
    """Install may skip a marked requirement that download would still fetch."""
    text = "greenlib==1.0.0 ; python_version < '3.9' \\\n    --hash=sha256:" + "a" * 64
    with pytest.raises(gate.GateError) as error:
        _options(text + "\n", tmp_path)
    assert error.value.code == gate.LOCK_SOURCE_UNSUPPORTED
    assert "environment markers" in str(error.value)


def test_a_directive_without_exactly_one_value_fails(tmp_path: Path) -> None:
    """A directive with no value, or several, is not a form this gate supports."""
    for line in ("--index-url", "--index-url a b"):
        with pytest.raises(gate.GateError) as error:
            _options(f"{line}\n{_PIN}", tmp_path)
        assert error.value.code == gate.LOCK_SOURCE_UNSUPPORTED


# ---------------------------------------------------------------------------
# The CLI the capture script calls
# ---------------------------------------------------------------------------


def test_the_cli_emits_one_validated_option_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One option per line keeps every value a single argv element in the caller."""
    (tmp_path / "wheels").mkdir()
    lock = tmp_path / "lock.txt"
    lock.write_text(f"--index-url https://pypi.org/simple\n--find-links wheels\n{_PIN}")
    assert (
        gate.main(
            [
                "lock-source-options",
                "--lock",
                str(lock),
                "--permitted-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == ["--index-url", "https://pypi.org/simple", "--find-links"]
    assert Path(lines[3]) == (tmp_path / "wheels").resolve()


def test_the_cli_exits_non_zero_on_an_untrusted_origin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The capture script checks this status explicitly, so it must be non-zero."""
    lock = tmp_path / "lock.txt"
    lock.write_text(f"--index-url https://packages.evil.invalid/simple\n{_PIN}")
    assert (
        gate.main(
            [
                "lock-source-options",
                "--lock",
                str(lock),
                "--permitted-root",
                str(tmp_path),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert gate.LOCK_SOURCE_ORIGIN_DENIED in captured.err
    # No option was emitted, so a caller reading stdout cannot proceed with a
    # partial list.
    assert captured.out == ""


def test_the_cli_leaks_no_credential_on_stdout_or_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A userinfo URL must not put credential material into any CI stream."""
    lock = tmp_path / "lock.txt"
    lock.write_text(f"--index-url https://bot:s3cr3t-T0KEN@pypi.org/simple\n{_PIN}")
    assert (
        gate.main(
            [
                "lock-source-options",
                "--lock",
                str(lock),
                "--permitted-root",
                str(tmp_path),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert gate.LOCK_SOURCE_CREDENTIAL_IN_URL in captured.err
    assert "s3cr3t-T0KEN" not in captured.err + captured.out
    assert "bot" not in captured.out


def test_the_cli_refuses_a_missing_lock(tmp_path: Path) -> None:
    """A lock that is not a regular file cannot be validated."""
    assert (
        gate.main(
            [
                "lock-source-options",
                "--lock",
                str(tmp_path / "absent.txt"),
                "--permitted-root",
                str(tmp_path),
            ]
        )
        == 2
    )


# ---------------------------------------------------------------------------
# The capture script wires the validator in fail-closed
# ---------------------------------------------------------------------------


_SCRIPT = Path("scripts/ci/release_dependency_capture_raw.sh")


def _executable_lines() -> list[str]:
    """Return the capture script's executable lines, comments removed."""
    return [
        line
        for line in _SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]


def test_the_capture_script_validates_directives_before_downloading() -> None:
    """Download must receive the validated options, not a directive-free file."""
    text = "\n".join(_executable_lines())
    assert "lock-source-options" in text
    assert '"${source_options[@]}"' in text
    validate_at = text.index("lock-source-options")
    download_at = text.index("download --no-deps")
    assert validate_at < download_at


def test_the_validator_status_is_checked_outside_process_substitution() -> None:
    """`mapfile < <(cmd)` would discard the refusal; the status must be explicit.

    This is the one way the fix could reproduce the very defect it removes: a
    validator that refuses, whose non-zero status is swallowed, reads as "no
    options" and collection silently continues from the default index.
    """
    text = "\n".join(_executable_lines())
    assert "mapfile -t source_options < <(" not in text
    assert 'if ! python3 -I "$gate_script" lock-source-options' in text
    assert 'mapfile -t source_options <"$options_file"' in text


def test_the_capture_script_resolves_the_gate_beside_itself() -> None:
    """The validator is the trusted sibling module, not a path from the lock."""
    text = "\n".join(_executable_lines())
    assert 'gate_script="$(cd -- "$(dirname -- "$0")" && pwd)/release_dependency_gate.py"' in text
    assert '[ -L "$gate_script" ]' in text


# ---------------------------------------------------------------------------
# The hash pin still decides, whatever source resolved the bytes
# ---------------------------------------------------------------------------


def test_source_options_never_change_the_pinned_hash_set(tmp_path: Path) -> None:
    """Adding a source directive must not alter which bytes the lock accepts.

    Source resolution decides *where* pip looks; the pin decides *what* is
    acceptable. `gate` compares each dependency's captured `source_sha256` against
    `parse_python_lock`'s hashes for that exact name and version, independently of
    the directives validated here, so an offline `--find-links` root cannot smuggle
    in a different artifact than install would have accepted.
    `test_red_tampered_source_hash` covers the tampered-bytes refusal itself.
    """
    (tmp_path / "wheels").mkdir()
    plain = gate.parse_python_lock(_PIN)
    with_directives = gate.parse_python_lock(
        f"--index-url https://pypi.org/simple\n--find-links wheels\n{_PIN}"
    )
    assert plain == with_directives
    assert plain == {("greenlib", "1.0.0"): frozenset({"a" * 64})}
    # And the directives themselves validate, so both facts hold at once.
    assert _options(
        f"--index-url https://pypi.org/simple\n--find-links wheels\n{_PIN}", tmp_path
    )[0] == "--index-url"


def test_download_keeps_hash_checking_disabled_so_the_gate_observes_mismatches(
    tmp_path: Path,
) -> None:
    """`pip download` must not pre-empt SOURCE_HASH_MISMATCH by verifying itself."""
    text = "\n".join(_executable_lines())
    download = [line for line in text.splitlines() if "download --no-deps" in line]
    assert download, "no pip download invocation found"
    assert not any("--require-hashes" in line for line in download)
    # Install, by contrast, must require hashes.
    install = [line for line in text.splitlines() if "inspect --local" in line]
    assert install


def test_a_bare_hash_line_is_not_treated_as_a_source_directive(tmp_path: Path) -> None:
    """A `--hash=` line that was not joined to its spec is still not a directive.

    Continuation joining normally attaches each hash to its requirement, but a lock
    whose spec line lacks the trailing backslash leaves `--hash=` standing alone.
    It starts with `-`, so it must be recognized and skipped rather than reported as
    an unsupported directive form.
    """
    text = "greenlib==1.0.0\n--hash=sha256:" + "a" * 64 + "\n"
    assert _options(text, tmp_path) == []
