"""Fail-first contracts for layout-preserving raw JSON log redaction."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import redact_sensitive_log as redactor

REPO_ROOT = Path(__file__).resolve().parents[1]


def _credential(suffix: str = "731") -> str:
    """Construct opaque credential material only at runtime."""
    return "-".join(("marble", "river", "opaque", suffix))


def test_atomic_json_redaction_cites_json_interoperability_standards() -> None:
    """Operators must find the JSON standards that justify span rewriting."""
    doctoring = (
        REPO_ROOT / "docs/doctoring/sandbox-log-redaction.md"
    ).read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "RFC 8259" in doctoring
    assert "unpredictable" in doctoring
    assert "ECMA-404" in doctoring
    assert "ISO/IEC 21778:2017" in doctoring
    assert "https://doi.org/10.17487/RFC8259" in doctoring
    assert "Bray, T. (Ed.). (2017)." in doctoring
    assert "Ecma International. (2017)." in doctoring
    assert "International Organization for Standardization. (2017)." in doctoring
    assert "RFC 3339" in doctoring
    assert "time-numoffset" in doctoring
    assert "HTAB" in doctoring
    assert "Klyne, G., & Newman, C. (2002)." in doctoring
    assert "https://doi.org/10.17487/RFC3339" in doctoring
    assert "Using workflow run logs" in doctoring
    assert "gh run view" in doctoring
    assert "UNKNOWN STEP" in doctoring
    assert "https://cli.github.com/manual/gh_run_view" in doctoring
    assert "begin-array" in doctoring
    assert "RFC 8259" in architecture
    assert "unpredictable" in architecture
    assert "ECMA-404" in architecture
    assert "ISO/IEC 21778" in architecture
    assert "RFC 3339" in architecture
    assert "runner timestamp" in architecture
    assert "time-numoffset" in architecture
    assert "HTAB" in architecture
    assert "gh run view" in architecture


def _timestamped_job_log(lines: tuple[str, ...], *, crlf: bool = False) -> str:
    """Prefix every Actions job-log line the way downloaded runner logs do."""
    ending = "\r\n" if crlf else "\n"
    stamped: list[str] = []
    for index, line in enumerate(lines):
        stamped.append(f"2026-08-16T15:22:12.001234{index}Z {line}")
    return ending.join(stamped) + ending


def _gh_run_view_log(
    lines: tuple[str, ...],
    *,
    job: str = "Exact-head sandbox redaction contract",
    step: str = "Verify fail-closed sandbox redaction contract",
    offset: str = "Z",
    separator: str = " ",
) -> str:
    """Prefix lines the way `gh run view --log-failed` copies zip logs."""
    stamped: list[str] = []
    for index, line in enumerate(lines):
        stamped.append(
            f"{job}\t{step}\t2026-08-16T15:22:12.001234{index}{offset}{separator}{line}"
        )
    return "\n".join(stamped) + "\n"


def test_realistic_actions_job_log_preserves_layout_and_hides_secrets() -> None:
    """A pretty-printed Actions evidence dump must keep layout and drop secrets."""
    first = _credential("actions")
    second = _credential("dup")
    source = _timestamped_job_log(
        (
            "##[group]Runner",
            "{",
            f'  "password": "{first}",',
            '  "status": "failed",',
            f'  "token": "{first}",',
            f'  "token": "{second}"',
            "}",
            "##[endgroup]",
        )
    )

    cleaned = redactor.redact_text(source)

    assert first not in cleaned
    assert second not in cleaned
    assert "##[group]Runner" in cleaned
    assert "##[endgroup]" in cleaned
    assert '"status": "failed"' in cleaned
    assert cleaned.count('"token"') == 2
    assert cleaned.count(f'"{redactor.REDACTED}"') == 3
    assert cleaned != redactor.REDACTED


def test_crlf_timestamped_job_log_preserves_group_and_status() -> None:
    """Downloaded Windows-style job logs keep group text after CRLF timestamps."""
    credential = _credential("crlf")
    source = _timestamped_job_log(
        (
            "##[error]schema",
            "{",
            f'  "password": "{credential}",',
            '  "status": "failed"',
            "}",
            "##[endgroup]",
        ),
        crlf=True,
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "##[error]schema" in cleaned
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned


def test_contiguous_group_marker_still_rewrites_only_credential_leaves() -> None:
    """Sandbox stdout that prints ##[group] then contiguous JSON stays visible."""
    credential = _credential("group")
    source = (
        "2026-08-16T15:22:12.001Z ##[group]Runner\n"
        "{\n"
        f'  "password": "{credential}",\n'
        '  "status": "failed"\n'
        "}\n"
        "2026-08-16T15:22:12.002Z ##[endgroup]\n"
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "##[group]Runner" in cleaned
    assert '"status": "failed"' in cleaned


def test_bracket_diagnostic_does_not_consume_later_sensitive_object() -> None:
    """A prose bracket must not fail-closed a later complete password object."""
    credential = _credential("timeout")
    source = f'retry [timeout]\n{{"password": "{credential}"}}\n'

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "retry [timeout]" in cleaned
    assert f'"password": "{redactor.REDACTED}"' in cleaned


def test_line_start_info_bracket_does_not_wipe_later_records() -> None:
    """A line-start [INFO] mentioning password must not erase later JSON."""
    credential = _credential("info")
    source = (
        '[INFO] schema requires "password": string\n'
        '[timeout] retry "password" probe\n'
        '{"status": "ok"}\n'
        f'{{"password": "{credential}"}}\n'
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert cleaned.startswith("[INFO] schema requires")
    assert "[timeout] retry" in cleaned
    assert '{"status": "ok"}' in cleaned
    assert f'"password": "{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_json_array_openers_still_parse_after_identifier_guard() -> None:
    """Literal JSON arrays remain spans after [INFO] is no longer an opener."""
    credential = _credential("array")
    source = (
        "[true,false,null,1]\n"
        "[false]\n"
        "[null]\n"
        f'[{{"password": "{credential}"}}]\n'
        "[]\n"
        "[\n"
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "[true,false,null,1]" in cleaned
    assert "[false]" in cleaned
    assert "[null]" in cleaned
    assert "[]" in cleaned
    assert cleaned.endswith("[\n")
    assert f'"password": "{redactor.REDACTED}"' in cleaned


def test_timestamped_pretty_printed_array_rewrites_only_leaves() -> None:
    """A downloaded pretty-printed array is one span despite per-line timestamps."""
    credential = _credential("arrts")
    source = _timestamped_job_log(
        (
            "[",
            f'  {{"password": "{credential}"}},',
            "  false,",
            "  null",
            "]",
        )
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "false" in cleaned
    assert "null" in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_rfc3339_offset_timestamped_job_log_keeps_group_and_status() -> None:
    """RFC 3339 time-numoffset prefixes must not fail-close a password object."""
    credential = _credential("offset")
    source = (
        "2026-08-16T15:22:12.0012340+00:00 ##[group]Runner\n"
        "2026-08-16T15:22:12.0012341+00:00 {\n"
        f'2026-08-16T15:22:12.0012342+00:00   "password": "{credential}",\n'
        '2026-08-16T15:22:12.0012343+00:00   "status": "failed"\n'
        "2026-08-16T15:22:12.0012344+00:00 }\n"
        "2026-08-16T15:22:12.0012345-07:00 ##[endgroup]\n"
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "##[group]Runner" in cleaned
    assert "##[endgroup]" in cleaned
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_tab_separated_timestamped_job_log_keeps_status() -> None:
    """A runner timestamp followed by HTAB must still leave one JSON span."""
    credential = _credential("tab")
    source = (
        "2026-08-16T15:22:12.0012340Z\t{\n"
        f'2026-08-16T15:22:12.0012341Z\t  "password": "{credential}",\n'
        '2026-08-16T15:22:12.0012342Z\t  "status": "failed"\n'
        "2026-08-16T15:22:12.0012343Z\t}\n"
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_gh_run_view_log_keeps_group_and_status() -> None:
    """Collector `gh run view --log-failed` job/step prefixes must stay visible."""
    credential = _credential("ghview")
    source = _gh_run_view_log(
        (
            "##[group]Runner",
            "{",
            f'  "password": "{credential}",',
            '  "status": "failed"',
            "}",
            "##[endgroup]",
        )
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "##[group]Runner" in cleaned
    assert "##[endgroup]" in cleaned
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_gh_run_view_unknown_step_offset_tab_keeps_status() -> None:
    """UNKNOWN STEP plus offset and HTAB must still leave one JSON span."""
    credential = _credential("unknown")
    source = _gh_run_view_log(
        (
            "{",
            f'  "password": "{credential}",',
            '  "status": "failed"',
            "}",
        ),
        job="Required OpenCode Review ContextualWisdomLab/.github#1040@df4b447f",
        step="UNKNOWN STEP",
        offset="+00:00",
        separator="\t",
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_two_tab_tsv_without_timestamp_is_not_eaten_as_runner_prefix() -> None:
    """A TSV diagnostic without an RFC 3339 prefix must keep its field text."""
    credential = _credential("tsv")
    source = f"name\tvalue\t{{\"password\": \"{credential}\", \"status\": \"failed\"}}\n"

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert cleaned.startswith("name\tvalue\t")
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned


def test_single_tab_line_inside_object_fails_closed() -> None:
    """A one-tab continuation is not a collector prefix and must not leak."""
    credential = _credential("onetab")
    source = "{\njob\tonly-one-field\n" f'  "password": "{credential}"\n}}\n'

    assert redactor.redact_text(source) == redactor.REDACTED


def test_two_tab_non_timestamp_line_inside_object_fails_closed() -> None:
    """Two tabs without an RFC 3339 timestamp must not be skipped as metadata."""
    credential = _credential("twotab")
    source = "{\njob\tstep\tnot-a-timestamp\n" f'  "password": "{credential}"\n}}\n'

    assert redactor.redact_text(source) == redactor.REDACTED


def test_gh_run_view_job_step_fields_redact_on_continuation_lines() -> None:
    """Skipped collector prefixes inside a span must still hide credential shapes."""
    token = "ghp_" + ("A" * 22)
    assignment_secret = _credential("asg")
    leaf = _credential("leaf")
    source = _gh_run_view_log(
        (
            "{",
            f'  "password": "{leaf}",',
            '  "status": "failed"',
            "}",
        ),
        job=token,
        step=f"password={assignment_secret}",
    )

    cleaned = redactor.redact_text(source)

    assert token not in cleaned
    assert assignment_secret not in cleaned
    assert leaf not in cleaned
    assert '"status": "failed"' in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_gh_run_view_array_rewrites_only_leaves() -> None:
    """A collector-prefixed pretty-printed array stays one span."""
    credential = _credential("gharr")
    source = _gh_run_view_log(
        (
            "[",
            f'  {{"password": "{credential}"}},',
            "  false,",
            "  null",
            "]",
        )
    )

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert "false" in cleaned
    assert "null" in cleaned
    assert f'"{redactor.REDACTED}"' in cleaned
    assert cleaned != redactor.REDACTED


def test_multiline_sensitive_value_is_rewritten_before_line_splitting() -> None:
    """Whitespace between key, colon, and value is preserved byte-for-byte."""
    credential = _credential()
    source = '{\n  "password"\n  :\n  "' + credential + '"\n}\n'
    expected = source.replace(credential, redactor.REDACTED)

    assert redactor.redact_text(source) == expected


def test_duplicate_sensitive_keys_preserve_order_count_and_layout() -> None:
    """Duplicate object members survive span rewriting without dict collapse."""
    first = _credential("first")
    second = _credential("second")
    source = (
        '{ "token" : "'
        + first
        + '", "status":"failed", "token" : "'
        + second
        + '" }'
    )

    cleaned = redactor.redact_text(source)

    assert first not in cleaned
    assert second not in cleaned
    assert cleaned.count('"token"') == 2
    assert cleaned.count(f'"{redactor.REDACTED}"') == 2
    assert cleaned.replace(f'"{redactor.REDACTED}"', '"VALUE"') == source.replace(
        f'"{first}"',
        '"VALUE"',
    ).replace(f'"{second}"', '"VALUE"')


def test_sensitive_scalar_categories_and_container_shape_are_preserved() -> None:
    """Sensitive JSON values keep type categories and recursive container shape."""
    credential = _credential()
    source = (
        '{"password":"'
        + credential
        + '","token":12,"secret":1.25,"auth":true,'
        '"credential":null,"private_key":["leaf",7,false,null,{"x":"y"}]}'
    )
    expected = (
        '{"password":"[REDACTED]","token":0,"secret":0.0,"auth":false,'
        '"credential":null,"private_key":["[REDACTED]",0,false,null,'
        '{"x":"[REDACTED]"}]}'
    )

    assert redactor.redact_text(source) == expected


def test_prefixed_and_multiple_json_records_preserve_untouched_slices() -> None:
    """Bounded structural spans can coexist with ordinary diagnostic text."""
    first = _credential("one")
    second = _credential("two")
    source = (
        "prefix diagnostic\n"
        f'{{\n  "password": "{first}"\n}}\n'
        "middle diagnostic\n"
        f'{{"token":"{second}","status":"failed"}}\n'
        "suffix diagnostic\n"
    )

    cleaned = redactor.redact_text(source)

    assert first not in cleaned
    assert second not in cleaned
    assert cleaned.startswith("prefix diagnostic\n{\n")
    assert "\n}\nmiddle diagnostic\n" in cleaned
    assert cleaned.endswith("\nsuffix diagnostic\n")
    assert '"status":"failed"' in cleaned


def test_malformed_multiline_sensitive_candidate_fails_closed() -> None:
    """A structural candidate spanning lines cannot fall back and leak its tail."""
    credential = _credential()
    source = '{\n "password"\n :\n "' + credential

    cleaned = redactor.redact_text(source)

    assert credential not in cleaned
    assert redactor.REDACTED in cleaned


def test_raw_json_limits_are_explicit_and_fail_closed() -> None:
    """Parser byte, depth, token, string, replacement, and work limits are fixed."""
    assert redactor.MAX_RAW_JSON_INPUT_BYTES == 65_536
    assert redactor.MAX_RAW_JSON_DEPTH == 64
    assert redactor.MAX_RAW_JSON_TOKENS == 8_192
    assert redactor.MAX_RAW_JSON_STRING_BYTES == 32_768
    assert redactor.MAX_RAW_JSON_REPLACEMENTS == 2_048
    assert redactor.MAX_RAW_JSON_WORK == 262_144

    oversized = '{"password":"' + "x" * redactor.MAX_RAW_JSON_INPUT_BYTES + '"}'
    assert redactor.redact_text(oversized) == redactor.REDACTED


def test_escaped_keys_empty_containers_and_layout_remain_unchanged() -> None:
    """Classification decodes tokens without normalizing untouched source slices."""
    credential = _credential("escaped")
    source = (
        '{"pa\\u0073sword" : "'
        + credential
        + '","note":"line\\nkept","empty_array":[],"empty_object":{}}'
    )
    expected = source.replace(credential, redactor.REDACTED)

    assert redactor.redact_text(source) == expected


def test_iterative_depth_and_replacement_limits_fail_closed() -> None:
    """Deep trees and excessive rewrite counts return one bounded marker."""
    deep = (
        '{"password":'
        + "[" * (redactor.MAX_RAW_JSON_DEPTH + 1)
        + '"leaf"'
        + "]" * (redactor.MAX_RAW_JSON_DEPTH + 1)
        + "}"
    )
    replacements = (
        '{"password":['
        + ",".join("1" for _ in range(redactor.MAX_RAW_JSON_REPLACEMENTS + 1))
        + "]}"
    )

    assert redactor.redact_text(deep) == redactor.REDACTED
    assert redactor.redact_text(replacements) == redactor.REDACTED


def test_token_limit_is_bounded_for_benign_high_volume_json() -> None:
    """Excessive benign token volume returns through bounded plain-text handling."""
    source = "[" + ",".join("0" for _ in range(5_000)) + "]"

    assert redactor.redact_text(source) == source


def test_oversized_benign_input_does_not_become_a_false_secret_finding() -> None:
    """The byte limit fails closed only when credential context is present."""
    source = '{"status":"' + "x" * redactor.MAX_RAW_JSON_INPUT_BYTES + '"}'

    assert redactor.redact_text(source) == source


def test_malformed_sensitive_json_states_fail_closed_without_diagnostics() -> None:
    """Every unsafe parser boundary emits only the stable redaction marker."""
    credential = _credential("malformed")
    malformed = (
        '{"password":',
        '{"password":xyz}',
        '{"password" "' + credential + '","token":}',
        '{"password":"' + credential + '", bad}',
        '{"password":1',
        '{"password":"\\q"}',
        '{"password":"' + credential + '\n"}',
        '{"password":"' + "x" * redactor.MAX_RAW_JSON_STRING_BYTES + '"}',
        '{"\\q":0,"password":',
    )

    for source in malformed:
        assert redactor.redact_text(source) == redactor.REDACTED, source
    assert redactor.redact_text('{"status":') == '{"status":'


def test_command_fields_preserve_json_shape_when_wrapper_fails_closed() -> None:
    """Command evidence keeps array shape even when its wrapper collapses evidence."""
    source = '{"command":"echo ok","argv":["sh","-c","   "]}'

    assert redactor.redact_text(source) == (
        '{"command":"echo ok","argv":'
        '["[REDACTED]","[REDACTED]","[REDACTED]"]}'
    )


def test_materialized_json_redaction_keeps_collision_and_command_contracts() -> None:
    """Trusted object redaction remains separate from raw layout preservation."""
    value = {
        "[REDACTED]#2": "kept",
        "alpha-secret": "first",
        "beta-secret": "second",
        "command": {"password": "nested"},
    }

    cleaned = redactor.redact_json_value(
        value,
        sensitive_values=("alpha-secret", "beta-secret"),
    )

    assert cleaned == {
        "[REDACTED]#2": "kept",
        "[REDACTED]": redactor.REDACTED,
        "[REDACTED]#3": redactor.REDACTED,
        "command": {"password": redactor.REDACTED},
    }
