"""Security contracts for bounded command-wrapper credential redaction."""

from __future__ import annotations

import json
import shlex

import pytest

from scripts.ci import redact_sensitive_log as redactor


def _credential() -> str:
    """Build an opaque credential at runtime without committing one fixture literal."""
    return "-".join(("river", "quartz", "credential", "731"))


@pytest.mark.parametrize(
    "option",
    ("-S", "--split-string"),
)
def test_env_split_string_operand_is_redacted(option: str) -> None:
    """GNU env split-string operands receive bounded nested argv redaction."""
    credential = _credential()
    cleaned = redactor.redact_command_argv(
        ["/usr/bin/env", option, f"docker login -p {credential}"]
    )

    assert credential not in cleaned[2]
    assert shlex.split(cleaned[2]) == [
        "docker",
        "login",
        "-p",
        redactor.REDACTED,
    ]


def test_env_split_string_equals_and_shell_nesting_are_redacted() -> None:
    """The long equals spelling can safely contain one nested shell wrapper."""
    credential = _credential()
    source = f"env --split-string=\"sh -c 'podman login -p {credential}'\""

    cleaned = redactor.redact_command_text(source)

    assert credential not in cleaned
    outer = shlex.split(cleaned)
    assert outer[0] == "env"
    assert outer[1].startswith("--split-string=")
    shell = shlex.split(outer[1].partition("=")[2])
    assert shell[:2] == ["sh", "-c"]
    assert shlex.split(shell[2]) == [
        "podman",
        "login",
        "-p",
        redactor.REDACTED,
    ]


def test_env_split_string_preserves_modifiers_before_nested_command() -> None:
    """Env assignments and unset options do not hide the actual nested program."""
    credential = _credential()
    operand = f"-u OLD_NAME MODE=diagnostic docker login -p {credential}"

    cleaned = redactor.redact_command_argv(["env", "-S", operand])

    nested = shlex.split(cleaned[2])
    assert nested[:4] == ["-u", "OLD_NAME", "MODE=diagnostic", "docker"]
    assert credential not in nested
    assert nested[-1] == redactor.REDACTED

    variants = (
        f"--unset=OLD_NAME --chdir=/tmp docker login -p {credential}",
        f"-i -- docker login -p {credential}",
    )
    for variant in variants:
        rendered = redactor.redact_command_argv(["env", "-S", variant])[2]
        assert credential not in rendered
        assert redactor.REDACTED in rendered

    assert redactor.redact_command_argv(["env", "-S", "-u"])[2] == "-u"
    assert redactor.redact_command_argv(["env", "-S", "MODE=diagnostic"])[
        2
    ] == "MODE=diagnostic"


@pytest.mark.parametrize("program", ("sh", "bash", "dash", "ksh", "zsh"))
@pytest.mark.parametrize("selector", ("-c", "-ec", "-lc"))
def test_shell_command_operands_are_redacted(program: str, selector: str) -> None:
    """Exact supported shell basenames and combined c selectors are handled."""
    credential = _credential()
    cleaned = redactor.redact_command_argv(
        [f"/bin/{program}", selector, f"docker login -p {credential}"]
    )

    assert credential not in cleaned[2]
    assert shlex.split(cleaned[2])[-1] == redactor.REDACTED


@pytest.mark.parametrize(
    "operand",
    (
        "docker login -p 'unterminated",
        "docker login -p value; echo unsafe",
        "docker login -p $VALUE",
        "docker login -p `lookup`",
        "docker login -p value\\next",
        "docker login -p value\nnext",
    ),
)
def test_unsupported_shell_operand_fails_closed(operand: str) -> None:
    """Malformed or compound shell grammar never publishes the nested operand."""
    assert redactor.redact_command_argv(["sh", "-c", operand]) == [
        redactor.REDACTED
    ]


@pytest.mark.parametrize(
    "source",
    (
        "sh -c 'docker login -p {credential}",
        "env -S 'docker login -p {credential}",
        'env --split-string="docker login -p {credential}',
    ),
)
def test_unterminated_outer_wrapper_quote_fails_closed(source: str) -> None:
    """Malformed public wrapper quoting never falls back to raw evidence."""
    credential = _credential()

    cleaned = redactor.redact_command_text(source.format(credential=credential))

    assert cleaned == redactor.REDACTED
    assert credential not in cleaned


def test_env_split_string_rejects_trailing_argv_and_expansion() -> None:
    """Ambiguous GNU env operand composition fails closed for all evidence."""
    credential = _credential()
    assert redactor.redact_command_argv(
        ["env", "-S", f"docker login -p {credential}", "trailing"]
    ) == [redactor.REDACTED]
    assert redactor.redact_command_argv(
        ["env", "--split-string", f"docker login -p ${credential}"]
    ) == [redactor.REDACTED]
    assert redactor.redact_command_argv(
        ["env", "--split-string", 'docker login -p "$VALUE"']
    ) == [redactor.REDACTED]
    assert redactor.redact_command_argv(
        ["env", "--split-string", "docker login -p value # comment"]
    ) == [redactor.REDACTED]
    assert redactor.redact_command_argv(
        ["env", "--split-string=",]
    ) == [redactor.REDACTED]


def test_shell_positional_argv_is_not_assumed_safe() -> None:
    """Unproven shell c positional mappings fail closed rather than leak argv."""
    credential = _credential()
    assert redactor.redact_command_argv(
        ["bash", "-c", "docker login -p placeholder", "name", credential]
    ) == [redactor.REDACTED]


def test_depth_bound_redacts_only_the_remaining_nested_operand() -> None:
    """The wrapper-depth boundary terminates with a bounded inner marker."""
    credential = _credential()
    operand = f"docker login -p {credential}"
    for _ in range(redactor.MAX_COMMAND_WRAPPER_DEPTH + 1):
        operand = shlex.join(["sh", "-c", operand])

    cleaned = redactor.redact_command_text(operand)

    assert credential not in cleaned
    assert redactor.REDACTED in cleaned
    assert cleaned != redactor.REDACTED


def test_fixed_ten_wrapper_tree_fails_closed_within_root_limit() -> None:
    """A ten-level quoted tree cannot evade the earlier root byte boundary."""
    operand = f"docker login -p {_credential()}"
    for _ in range(10):
        operand = shlex.join(["sh", "-c", operand])

    assert redactor.redact_command_text(operand) == redactor.REDACTED


def test_command_input_and_token_limits_fail_closed() -> None:
    """Root byte and shared token limits have exact accepted/rejected edges."""
    accepted = "x" * redactor.MAX_COMMAND_INPUT_BYTES
    rejected = accepted + "x"

    assert redactor.redact_command_text(accepted) == accepted
    assert redactor.redact_command_text(rejected) == redactor.REDACTED
    assert redactor.redact_command_argv([rejected]) == [redactor.REDACTED]
    assert redactor.redact_command_argv(
        ["tool", *(["arg"] * (redactor.MAX_COMMAND_TOKENS - 1))]
    )[0] == "tool"
    assert redactor.redact_command_argv(
        ["tool", *(["arg"] * redactor.MAX_COMMAND_TOKENS)]
    ) == [redactor.REDACTED]


def test_command_cumulative_work_limit_is_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested rescans consume one root-owned work budget."""
    credential = _credential()
    source = shlex.join(
        ["sh", "-c", shlex.join(["sh", "-c", f"docker login -p {credential}"])]
    )

    monkeypatch.setattr(redactor, "MAX_COMMAND_WORK", 60)
    assert redactor.redact_command_text(source) == redactor.REDACTED
    monkeypatch.setattr(redactor, "MAX_COMMAND_WORK", 100)
    assert redactor.redact_command_text(source) == redactor.REDACTED

    flat = "docker login -p " + credential
    assert redactor.redact_command_text(flat) != redactor.REDACTED


def test_container_login_detection_has_no_option_false_positives() -> None:
    """Only the exact login subcommand gives short p password semantics."""
    credential = _credential()

    assert redactor.redact_command_argv(
        ["docker", "login", "--password-stdin", "registry.example"]
    ) == ["docker", "login", "--password-stdin", "registry.example"]
    assert redactor.redact_command_argv(
        ["docker", "login", f"--password-stdin={credential}"]
    ) == ["docker", "login", f"--password-stdin={redactor.REDACTED}"]
    assert redactor.redact_command_argv(
        ["docker", "run", "--name", "login", "-p", "8080:80", "image"]
    ) == ["docker", "run", "--name", "login", "-p", "8080:80", "image"]
    assert redactor.redact_command_argv(
        ["docker", "run", "login", "-p", "8080:80", "image"]
    ) == ["docker", "run", "login", "-p", "8080:80", "image"]
    assert redactor.redact_command_argv(["ssh", "-p", "22", "host"])[2] == "22"


def test_benign_env_controls_and_assignments_remain_visible() -> None:
    """Non-splitting env options are ordinary evidence, not nested commands."""
    command = [
        "env",
        "-u",
        "OLD_NAME",
        "--unset=OTHER_NAME",
        "-C",
        "/tmp",
        "--chdir=/workspace",
        "MODE=diagnostic",
        "printf",
        "ok",
    ]

    assert redactor.redact_command_argv(command) == command


def test_non_wrapper_and_incomplete_wrapper_forms_remain_bounded() -> None:
    """Wrapper recognition requires an exact supported option and operand position."""
    assert redactor.redact_command_argv([]) == []
    assert redactor.redact_command_argv(["env"]) == ["env"]
    assert redactor.redact_command_argv(["env", "-u"]) == ["env", "-u"]
    assert redactor.redact_command_argv(["env", "--debug"]) == ["env", "--debug"]
    assert redactor.redact_command_argv(["env", "printf", "ok"]) == [
        "env",
        "printf",
        "ok",
    ]
    assert redactor.redact_command_argv(["sh"]) == ["sh"]
    assert redactor.redact_command_argv(["sh", "-e"]) == ["sh", "-e"]
    assert redactor.redact_command_argv(["sh", "--", "script.sh"]) == [
        "sh",
        "--",
        "script.sh",
    ]
    assert redactor.redact_command_argv(["sh", "script.sh"]) == [
        "sh",
        "script.sh",
    ]


def test_empty_nested_operand_and_unsafe_root_controls_fail_closed() -> None:
    """Empty wrapper commands and render controls never reach published evidence."""
    assert redactor.redact_command_argv(["sh", "-c", "   "]) == [
        redactor.REDACTED
    ]
    assert redactor.redact_command_text("tool\x1b]2;title\x07 arg") == redactor.REDACTED


def test_json_command_fields_use_the_same_bounded_wrapper_contract() -> None:
    """Structured command evidence cannot bypass nested wrapper redaction."""
    credential = _credential()
    source = json.dumps(
        {
            "command": f"sh -c 'docker login -p {credential}'",
            "argv": ["docker", "login", "-p", credential],
            "backend_cmd": 7,
            "status": "failed",
        }
    )

    cleaned = json.loads(redactor.redact_text(source))

    assert credential not in cleaned["command"]
    assert redactor.REDACTED in cleaned["command"]
    assert cleaned["argv"][-1] == redactor.REDACTED
    assert cleaned["backend_cmd"] == 7
    assert cleaned["status"] == "failed"
    shell_json = redactor.redact_command_argv(
        ["sh", "-c", f"tool --payload '{{\"password\":\"{credential}\"}}'"]
    )
    assert credential not in " ".join(shell_json)
    assert redactor.REDACTED in " ".join(shell_json)
