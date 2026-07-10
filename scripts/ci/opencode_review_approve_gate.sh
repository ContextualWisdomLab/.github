#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 4 ] && [ $# -ne 5 ]; then
  echo "usage: $0 <expected_head_sha> <expected_run_id> <expected_run_attempt> <comment_body_file> [normalized_json_file]" >&2
  exit 64
fi

SCRIPT_DIR="$(
  CDPATH=''
  cd -P -- "$(dirname -- "$0")"
  pwd -P
)"
NORMALIZER="$SCRIPT_DIR/opencode_review_normalize_output.py"
EXPECTED_HEAD_SHA="$1"
EXPECTED_RUN_ID="$2"
EXPECTED_RUN_ATTEMPT="$3"
COMMENT_FILE="$4"
NORMALIZED_JSON_FILE="${5:-}"

if [ ! -r "$COMMENT_FILE" ]; then
  echo "error: cannot read comment body file: $COMMENT_FILE" >&2
  exit 65
fi

SENTINEL_LINE="$(
  grep -E '<!--[[:space:]]+opencode-review-gate[[:space:]]+head_sha=[^[:space:]]+[[:space:]]+run_id=[^[:space:]]+[[:space:]]+run_attempt=[^[:space:]]+[[:space:]]+-->' \
    "$COMMENT_FILE" | head -1 || true
)"

if [ -z "$SENTINEL_LINE" ]; then
  echo "MISSING_SENTINEL"
  exit 2
fi

SENTINEL_HEAD_SHA="$(echo "$SENTINEL_LINE" | sed -nE 's/.*head_sha=([^[:space:]]+).*/\1/p')"
SENTINEL_RUN_ID="$(echo "$SENTINEL_LINE" | sed -nE 's/.*run_id=([^[:space:]]+).*/\1/p')"
SENTINEL_RUN_ATTEMPT="$(echo "$SENTINEL_LINE" | sed -nE 's/.*run_attempt=([^[:space:]]+).*/\1/p')"

if [ "$SENTINEL_HEAD_SHA" != "$EXPECTED_HEAD_SHA" ]; then
  echo "SHA_MISMATCH"
  exit 3
fi

if [ -z "$SENTINEL_RUN_ID" ] || [ -z "$SENTINEL_RUN_ATTEMPT" ]; then
  echo "MISSING_SENTINEL"
  exit 2
fi

if [ "$EXPECTED_RUN_ID" != "-" ] && [ "$SENTINEL_RUN_ID" != "$EXPECTED_RUN_ID" ]; then
  echo "MISSING_SENTINEL"
  exit 2
fi

if [ "$EXPECTED_RUN_ATTEMPT" != "-" ] && [ "$SENTINEL_RUN_ATTEMPT" != "$EXPECTED_RUN_ATTEMPT" ]; then
  echo "MISSING_SENTINEL"
  exit 2
fi

CONTROL_JSON="$(
  awk '
    /^<!--[[:space:]]*opencode-review-control-v1[[:space:]]*$/ { in_block=1; next }
    in_block && /^-->[[:space:]]*$/ { exit }
    in_block { print }
  ' "$COMMENT_FILE"
)"

if [ -z "$CONTROL_JSON" ]; then
  echo "NO_CONCLUSION"
  exit 4
fi

TMP_JSON="$(mktemp)"
TMP_FIELDS="$(mktemp)"
trap 'rm -f "$TMP_JSON" "$TMP_FIELDS"' EXIT
printf '%s\n' "$CONTROL_JSON" >"$TMP_JSON"

if ! python3 - "$TMP_JSON" >"$TMP_FIELDS" <<'PY'
from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def fail() -> None:
    raise SystemExit(1)


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and len(value) > 0


def valid_finding(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    path = value.get("path")
    if not nonempty_string(path):
        return False
    if str(path).casefold() in {"n/a", "unknown"}:
        return False
    line = value.get("line")
    if (
        isinstance(line, bool)
        or not isinstance(line, (int, float))
        or not math.isfinite(float(line))
        or line <= 0
        or math.floor(float(line)) != float(line)
    ):
        return False
    required_strings = (
        "severity",
        "title",
        "problem",
        "root_cause",
        "fix_direction",
        "regression_test_direction",
        "suggested_diff",
    )
    if not all(nonempty_string(value.get(field)) for field in required_strings):
        return False
    suggested_diff = str(value.get("suggested_diff", "")).casefold()
    if suggested_diff.startswith("n/a") or suggested_diff.startswith("cannot provide diff"):
        return False
    return True


try:
    control = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    fail()

if not isinstance(control, dict):
    fail()

if not all(nonempty_string(control.get(field)) for field in ("head_sha", "run_id", "run_attempt", "reason", "summary")):
    fail()

result = control.get("result")
if result not in {"APPROVE", "REQUEST_CHANGES"}:
    fail()

findings = control.get("findings")
if result == "REQUEST_CHANGES":
    if not isinstance(findings, list) or len(findings) == 0:
        fail()
elif findings is not None and (not isinstance(findings, list) or len(findings) != 0):
    fail()

if not all(valid_finding(finding) for finding in (findings or [])):
    fail()

print(control["head_sha"])
print(control["run_id"])
print(control["run_attempt"])
print(result)
PY
then
  echo "NO_CONCLUSION"
  exit 4
fi

mapfile -t CONTROL_FIELDS <"$TMP_FIELDS"
if [ "${#CONTROL_FIELDS[@]}" -ne 4 ]; then
  echo "NO_CONCLUSION"
  exit 4
fi

CONTROL_HEAD_SHA="${CONTROL_FIELDS[0]%$'\r'}"
CONTROL_RUN_ID="${CONTROL_FIELDS[1]%$'\r'}"
CONTROL_RUN_ATTEMPT="${CONTROL_FIELDS[2]%$'\r'}"
RESULT="${CONTROL_FIELDS[3]%$'\r'}"

if [ "$CONTROL_HEAD_SHA" != "$EXPECTED_HEAD_SHA" ]; then
  echo "SHA_MISMATCH"
  exit 3
fi

if [ "$EXPECTED_RUN_ID" != "-" ] && [ "$CONTROL_RUN_ID" != "$EXPECTED_RUN_ID" ]; then
  echo "MISSING_SENTINEL"
  exit 2
fi

if [ "$EXPECTED_RUN_ATTEMPT" != "-" ] && [ "$CONTROL_RUN_ATTEMPT" != "$EXPECTED_RUN_ATTEMPT" ]; then
  echo "MISSING_SENTINEL"
  exit 2
fi

if ! python3 "$NORMALIZER" --check-structural-approval "$TMP_JSON" >/dev/null; then
  echo "NO_CONCLUSION"
  exit 4
fi

SOURCE_ROOT="${OPENCODE_SOURCE_WORKDIR:-${GITHUB_WORKSPACE:-$PWD}}"
PR_BASE_SHA_VAR="${PR_BASE_SHA:-}"
PR_HEAD_SHA_VAR="${PR_HEAD_SHA:-${HEAD_SHA:-}}"
if ! python3 - "$SOURCE_ROOT" "$TMP_JSON" "$PR_BASE_SHA_VAR" "$PR_HEAD_SHA_VAR" <<'PY'
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


source_root = Path(sys.argv[1]).resolve()
control_file = Path(sys.argv[2])
control = json.loads(control_file.read_text(encoding="utf-8"))
pr_base_sha = sys.argv[3].strip() if len(sys.argv) > 3 else ""
pr_head_sha = sys.argv[4].strip() if len(sys.argv) > 4 else ""

if control.get("result") != "REQUEST_CHANGES":
    raise SystemExit(0)


def normalized_line(value: str) -> str:
    return " ".join(value.strip().split())


def changed_new_lines(path_value: str) -> set[int]:
    if not pr_base_sha or not pr_head_sha:
        return set()
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(source_root),
                "diff",
                "--unified=0",
                "--no-ext-diff",
                pr_base_sha,
                pr_head_sha,
                "--",
                path_value,
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
    except OSError:
        return set()
    if completed.returncode not in {0, 1}:
        return set()

    line_numbers: set[int] = set()
    hunk_header = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    for raw_line in completed.stdout.splitlines():
        match = hunk_header.match(raw_line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        if count <= 0:
            continue
        line_numbers.update(range(start, start + count))
    return line_numbers


_file_cache: dict[Path, list[str]] = {}


def finding_is_source_backed(finding: dict[str, object]) -> bool:
    path_value = str(finding.get("path", ""))
    if (
        not path_value
        or path_value.startswith("/")
        or path_value == "."
        or ".." in Path(path_value).parts
    ):
        return False

    source_file = (source_root / path_value).resolve()
    try:
        source_file.relative_to(source_root)
    except ValueError:
        return False
    if not source_file.is_file():
        return False

    try:
        if source_file not in _file_cache:
            _file_cache[source_file] = source_file.read_text(encoding="utf-8").splitlines()
        source_lines = _file_cache[source_file]
    except UnicodeDecodeError:
        return False

    line_number = finding.get("line")
    if not isinstance(line_number, int) or line_number < 1 or line_number > len(source_lines):
        return False
    if line_number not in changed_new_lines(path_value):
        return False

    source_line_set = {
        normalized_line(line)
        for line in source_lines
        if normalized_line(line)
    }
    suggested_diff = str(finding.get("suggested_diff", ""))
    removed_lines = []
    added_lines = []
    for raw_line in suggested_diff.splitlines():
        if raw_line.startswith("--- ") or raw_line.startswith("+++ "):
            continue
        if raw_line.startswith("-"):
            stripped = normalized_line(raw_line[1:])
            if stripped:
                removed_lines.append(stripped)
        elif raw_line.startswith("+"):
            stripped = normalized_line(raw_line[1:])
            if stripped:
                added_lines.append(stripped)

    if not removed_lines and not added_lines:
        return False
    for removed_line in removed_lines:
        if removed_line not in source_line_set:
            return False
    return True


for finding in control.get("findings", []):
    if finding_is_source_backed(finding):
        continue
    path_value = str(finding.get("path", "<missing-path>"))
    line_value = finding.get("line", "<missing-line>")
    title_value = str(finding.get("title", "<missing-title>"))
    print(
        "REQUEST_CHANGES finding is not source-backed by the current-head diff: "
        f"{path_value}:{line_value} {title_value}",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
then
  echo "NO_CONCLUSION"
  exit 4
fi

if [ -n "$NORMALIZED_JSON_FILE" ]; then
  if ! python3 - "$TMP_JSON" "$NORMALIZED_JSON_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


control = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
normalized = {
    "head_sha": control["head_sha"],
    "run_id": control["run_id"],
    "run_attempt": control["run_attempt"],
    "result": control["result"],
    "reason": control["reason"],
    "summary": control["summary"],
    "findings": control.get("findings") or [],
}
Path(sys.argv[2]).write_text(
    json.dumps(normalized, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
  then
    echo "NO_CONCLUSION"
    exit 4
  fi
fi

echo "$RESULT"
exit 0
