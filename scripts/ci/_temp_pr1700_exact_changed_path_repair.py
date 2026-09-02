#!/usr/bin/env python3
"""Materialize PR #1700's exact changed-path evidence contract on current main."""

from __future__ import annotations

from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment and fail closed on drift."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def remove_tests_containing(path: str, needles: tuple[str, ...]) -> None:
    """Retire tests whose complete function body asserts superseded heuristics."""
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?ms)^((?:@pytest[^\n]*\n|@pytest\.mark\.parametrize\(.*?\)\n)*)def (test_[A-Za-z0-9_]+)\([^\n]*\).*?(?=^(?:@pytest|def test_|class )|\Z)"
    )
    text = pattern.sub(
        lambda match: "" if any(needle in match.group(0) for needle in needles) else match.group(0),
        text,
    )
    target.write_text(text, encoding="utf-8")


gate_path = Path("scripts/ci/noema_review_gate.py")
gate = gate_path.read_text(encoding="utf-8")

gate = replace_once(
    gate,
    "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n",
    "",
    "filename-derived materiality import",
)
for constant in (
    "MAX_DIFF_CHARS = 60000\n",
    "MAX_CONTEXT_FILES = 12\n",
    "MAX_FILE_CONTEXT_CHARS = 4000\n",
    "MAX_REVIEW_CONTEXT_CHARS = 24000\n",
    "MAX_THREAD_BODY_CHARS = 1200\n",
):
    gate = replace_once(gate, constant, "", constant.strip())

schema_pattern = re.compile(
    r"def _noema_verdict_json_schema\(required_probes: int\) -> dict\[str, Any\]:\n.*?(?=\n\nclass NoemaModelOutputError)",
    re.S,
)
schema_replacement = '''def _noema_verdict_json_schema() -> dict[str, Any]:
    """Build the verdict schema without a caller-authored evidence-count floor."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"type": "string", "enum": ["approve", "request_changes", "comment"]},
            "summary": {"type": "string"},
            "reviewed_lines": {"type": ["array", "null"], "items": _NOEMA_REVIEWED_LINE_SCHEMA},
            "adversarial_validation": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["passed", "failed"]},
                    "residual_risk": {"type": "string"},
                    "probes": {"type": "array", "items": _NOEMA_PROBE_SCHEMA},
                },
                "required": ["status", "residual_risk", "probes"],
            },
            "findings": {"type": "array", "items": _NOEMA_FINDING_SCHEMA},
        },
        "required": ["decision", "summary", "reviewed_lines", "adversarial_validation", "findings"],
    }


def _noema_verdict_response_format() -> dict[str, Any]:
    """Build the OpenAI-compatible structured-output envelope."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "noema_review_verdict",
            "strict": True,
            "schema": _noema_verdict_json_schema(),
        },
    }


def _schema_max_container_depth(schema: dict[str, Any]) -> int:
    """Derive maximum object/array nesting from the declared verdict schema."""
    schema_type = schema.get("type")
    type_values = {schema_type} if isinstance(schema_type, str) else set(schema_type or ())
    own_depth = 1 if type_values.intersection({"object", "array"}) else 0
    children: list[dict[str, Any]] = []
    properties = schema.get("properties")
    if isinstance(properties, dict):
        children.extend(child for child in properties.values() if isinstance(child, dict))
    items = schema.get("items")
    if isinstance(items, dict):
        children.append(items)
    return own_depth + max((_schema_max_container_depth(child) for child in children), default=0)
'''
gate, count = schema_pattern.subn(schema_replacement, gate, count=1)
if count != 1:
    raise SystemExit(f"verdict schema block drifted: {count} matches")

fetch_diff_pattern = re.compile(
    r"def fetch_diff\(repo: str, number: int\) -> tuple\[str, bool\]:\n.*?(?=\n\ndef changed_diff_locations)",
    re.S,
)
fetch_diff_replacement = '''def fetch_diff(repo: str, number: int) -> tuple[str, bool]:
    """Fetch the complete immutable PR diff without caller-side evidence sampling."""
    diff = run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}",
            "-H",
            "Accept: application/vnd.github.v3.diff",
        ]
    )
    return diff, False
'''
gate, count = fetch_diff_pattern.subn(fetch_diff_replacement, gate, count=1)
if count != 1:
    raise SystemExit(f"fetch_diff block drifted: {count} matches")

required_pattern = re.compile(
    r"def _required_probe_count\(diff: str, changed_paths: Sequence\[str\] = \(\)\) -> int:\n.*?(?=\n\ndef _entry_ordinal)",
    re.S,
)
required_replacement = '''def _required_changed_paths(
    diff: str, changed_paths: Sequence[str] = ()
) -> set[str]:
    """Return the exact Git/GitHub changed-path universe a formal verdict must cover."""
    locations = changed_diff_locations(diff)
    supplied = {str(path) for path in changed_paths if str(path)}
    return supplied or {path for path, _line, _side in locations}
'''
gate, count = required_pattern.subn(required_replacement, gate, count=1)
if count != 1:
    raise SystemExit(f"probe-count function drifted: {count} matches")

anchor = '''    if not locations:\n        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")\n\n    reviewed_lines = verdict.get("reviewed_lines")\n'''
replacement = '''    if not locations:\n        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")\n    required_paths = _required_changed_paths(diff, changed_paths)\n    location_paths = {path for path, _line, _side in locations}\n    if not required_paths or not required_paths.issubset(location_paths):\n        raise NoemaModelOutputError(\n            "Noema formal verdict cannot cover every changed path with exact changed-side evidence"\n        )\n\n    reviewed_lines = verdict.get("reviewed_lines")\n'''
gate = replace_once(gate, anchor, replacement, "validator required changed paths")
gate = replace_once(
    gate,
    "    reviewed_total = len(reviewed_lines)\n    for position, reviewed in enumerate(reviewed_lines, start=1):\n",
    "    reviewed_total = len(reviewed_lines)\n    reviewed_paths: set[str] = set()\n    for position, reviewed in enumerate(reviewed_lines, start=1):\n",
    "reviewed path accumulator",
)
gate = replace_once(
    gate,
    '''        if not isinstance(analysis, str) or not analysis.strip():\n            raise NoemaModelOutputError(f"Noema reviewed line {entry} requires concrete analysis")\n\n    validation = verdict.get("adversarial_validation")\n''',
    '''        if not isinstance(analysis, str) or not analysis.strip():\n            raise NoemaModelOutputError(f"Noema reviewed line {entry} requires concrete analysis")\n        reviewed_paths.add(str(reviewed["path"]))\n    if not required_paths.issubset(reviewed_paths):\n        raise NoemaModelOutputError("Noema reviewed-line evidence must cover every changed path")\n\n    validation = verdict.get("adversarial_validation")\n''',
    "reviewed path coverage",
)
gate = replace_once(
    gate,
    '''    probes = validation.get("probes")\n    required_probes = _required_probe_count(diff, changed_paths)\n    if not isinstance(probes, list) or len(probes) < required_probes:\n        raise NoemaModelOutputError(\n            f"Noema adversarial validation requires at least {required_probes} concrete probe(s)"\n        )\n\n    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n''',
    '''    probes = validation.get("probes")\n    if not isinstance(probes, list):\n        raise NoemaModelOutputError("Noema adversarial validation probes must be a list")\n\n    confirmed: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    probe_paths: set[str] = set()\n''',
    "retire probe count and collect probe paths",
)
gate = replace_once(
    gate,
    '''        if identity in identities:\n            raise NoemaModelOutputError(f"Noema adversarial probe {entry} duplicates an earlier probe")\n        identities.add(identity)\n        if outcome == "confirmed":\n''',
    '''        if identity in identities:\n            raise NoemaModelOutputError(f"Noema adversarial probe {entry} duplicates an earlier probe")\n        identities.add(identity)\n        probe_paths.add(str(probe["path"]))\n        if outcome == "confirmed":\n''',
    "probe path accumulator",
)
gate = replace_once(
    gate,
    '''    if decision == "approve" and confirmed:\n        raise NoemaModelOutputError("Noema approve cannot contain a confirmed adversarial probe")\n''',
    '''    if not required_paths.issubset(probe_paths):\n        raise NoemaModelOutputError("Noema adversarial probe evidence must cover every changed path")\n\n    if decision == "approve" and confirmed:\n        raise NoemaModelOutputError("Noema approve cannot contain a confirmed adversarial probe")\n''',
    "probe path coverage",
)

truncate_pattern = re.compile(
    r"\n\ndef truncate_text\(text: str, limit: int\) -> str:\n.*?(?=\n\ndef fetch_changed_files)",
    re.S,
)
gate, count = truncate_pattern.subn("", gate, count=1)
if count != 1:
    raise SystemExit(f"truncate_text block drifted: {count} matches")

gate = replace_once(
    gate,
    '        f"`{merge_base_sha}`:]\\n{truncate_text(content, MAX_FILE_CONTEXT_CHARS)}"\n',
    '        f"`{merge_base_sha}`:]\\n{content}"\n',
    "removed-file full context",
)
gate = replace_once(
    gate,
    '    if any(status == "removed" for _path, status in files[:MAX_CONTEXT_FILES]):\n',
    '    if any(status == "removed" for _path, status in files):\n',
    "removed-file full path scan",
)
gate = replace_once(
    gate,
    '    for path, status in files[:MAX_CONTEXT_FILES]:\n',
    '    for path, status in files:\n',
    "changed-file full path coverage",
)
gate = replace_once(
    gate,
    '        sections.append(f"### {path}\\n{truncate_text(content, MAX_FILE_CONTEXT_CHARS)}")\n',
    '        sections.append(f"### {path}\\n{content}")\n',
    "changed-file full content",
)
omitted = '''    if len(files) > MAX_CONTEXT_FILES:\n        sections.append(f"[{len(files) - MAX_CONTEXT_FILES} changed files omitted from context budget]")\n'''
gate = replace_once(gate, omitted, "", "omitted-file marker")
gate = replace_once(
    gate,
    '            body = truncate_text(str(comment.get("body") or "").strip(), MAX_THREAD_BODY_CHARS)\n',
    '            body = str(comment.get("body") or "").strip()\n',
    "review-thread full body",
)
gate = replace_once(
    gate,
    '    return truncate_text("\\n\\n".join(sections), MAX_REVIEW_CONTEXT_CHARS)\n',
    '    return "\\n\\n".join(sections)\n',
    "review-context full evidence",
)
gate = replace_once(gate, "\nMAX_JSON_NESTING_DEPTH = 100\n", "\n", "arbitrary JSON depth")
gate = replace_once(
    gate,
    "if not _json_nesting_within_bound(stripped, start, MAX_JSON_NESTING_DEPTH):",
    "if not _json_nesting_within_bound(\n            stripped, start, _schema_max_container_depth(_noema_verdict_json_schema())\n        ):",
    "schema-derived preparse depth",
)
gate = replace_once(
    gate,
    'f"JSON nesting exceeds the bounded limit ({MAX_JSON_NESTING_DEPTH} levels)",',
    '"JSON nesting exceeds the declared verdict schema container depth",',
    "schema-derived depth diagnostic",
)
gate = gate.replace(
    '``MAX_JSON_NESTING_DEPTH`` (100 — generously above the\n    verdict schema\'s own real maximum of roughly 5 levels: object ->',
    'the container depth derived from ``_noema_verdict_json_schema()``. The\n    accepted depth follows the declared verdict schema: object ->',
)
gate = replace_once(
    gate,
    '                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",\n',
    '                "Every formal verdict must cite exact changed-side lines. APPROVE and REQUEST_CHANGES must include reviewed-line analysis and adversarial probes covering every changed path supplied by Git/GitHub; do not infer review effort from file names or extensions. REQUEST_CHANGES requires a confirmed probe at a finding location.",\n',
    "prompt changed-path coverage",
)
response_pattern = re.compile(
    r'        "response_format": _noema_verdict_response_format\(\n            _required_probe_count\(diff, changed_paths\)\n        \),\n'
)
gate, count = response_pattern.subn('        "response_format": _noema_verdict_response_format(),\n', gate, count=1)
if count != 1:
    raise SystemExit(f"response format call drifted: {count} matches")
gate = gate.replace("for finding in findings[:20]:", "for finding in findings:")
gate = gate.replace(
    'for reviewed in (verdict.get("reviewed_lines") or [])[:20]:',
    'for reviewed in (verdict.get("reviewed_lines") or []):',
)
gate = gate.replace(
    'for probe in (validation.get("probes") or [])[:20]:',
    'for probe in (validation.get("probes") or []):',
)

forbidden = (
    "MAX_DIFF_CHARS",
    "MAX_CONTEXT_FILES",
    "MAX_FILE_CONTEXT_CHARS",
    "MAX_REVIEW_CONTEXT_CHARS",
    "MAX_THREAD_BODY_CHARS",
    "changed_file_is_material",
    "_required_probe_count",
    "[:20]",
    "MAX_JSON_NESTING_DEPTH = 100",
)
remaining = [token for token in forbidden if token in gate]
if remaining:
    raise SystemExit(f"Noema evidence-allocation heuristics remain: {remaining}")
gate_path.write_text(gate, encoding="utf-8")

remove_tests_containing(
    "tests/test_noema_review_gate.py",
    (
        "MAX_DIFF_CHARS",
        "MAX_CONTEXT_FILES",
        "MAX_FILE_CONTEXT_CHARS",
        "MAX_REVIEW_CONTEXT_CHARS",
        "MAX_THREAD_BODY_CHARS",
        "_required_probe_count",
        "changed_file_is_material",
        "at least 2 concrete probe",
        "minItems",
    ),
)
remove_tests_containing(
    "tests/test_repository_branch_coverage_javascript_and_noema.py",
    ("MAX_DIFF_CHARS",),
)
remove_tests_containing(
    "tests/test_noema_repair_attempt_telemetry.py",
    ("_required_probe_count", "minItems", "probe_floor"),
)
for test_path in (
    Path("tests/test_noema_review_gate.py"),
    Path("tests/test_noema_repair_attempt_telemetry.py"),
):
    if not test_path.exists():
        continue
    text = test_path.read_text(encoding="utf-8")
    text = re.sub(r"noema\._noema_verdict_json_schema\([^\n)]*\)", "noema._noema_verdict_json_schema()", text)
    text = re.sub(r"noema\._noema_verdict_response_format\([^\n)]*\)", "noema._noema_verdict_response_format()", text)
    text = text.replace(
        "noema.MAX_JSON_NESTING_DEPTH",
        "noema._schema_max_container_depth(noema._noema_verdict_json_schema())",
    )
    test_path.write_text(text, encoding="utf-8")

doctoring_path = Path("docs/doctoring/noema-repair-attempt-telemetry.md")
doctoring = doctoring_path.read_text(encoding="utf-8")
marker = "## 2026-09-02 exact changed-path evidence allocation correction"
if marker not in doctoring:
    doctoring += '''\n\n## 2026-09-02 exact changed-path evidence allocation correction\n\nThe earlier one-versus-two adversarial-probe rule and fixed diff/file/thread context caps were not derived from a statistical model, provider-capability contract, GitHub protocol, or review-quality experiment. Noema now preserves the complete Git diff, changed-file text, and review-thread evidence it retrieves. A formal `approve` or `request_changes` verdict is admissible only when reviewed-line analysis and adversarial probes cover the exact changed-path set supplied by Git/GitHub. Filename or extension classification no longer allocates review effort. If `contextual-orchestrator` or the serving provider cannot accept the complete request, the request fails closed instead of silently sampling evidence.\n\nThe JSON pre-decode nesting guard remains fail-closed but derives its container depth from the declared verdict schema. Finding and evidence rendering no longer suppresses entries through a fixed slice.\n'''
    doctoring_path.write_text(doctoring, encoding="utf-8")

changelog_path = Path("CHANGELOG.md")
changelog = changelog_path.read_text(encoding="utf-8")
note = "- Noema review evidence allocation now preserves complete fetched evidence, requires exact changed-path set coverage, derives JSON nesting depth from its verdict schema, and removes filename/count/display-slice heuristics.\n"
if note not in changelog:
    changelog_path.write_text(note + changelog, encoding="utf-8")
