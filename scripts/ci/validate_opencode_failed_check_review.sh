#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <control-json-file> <failed-checks-file> <failed-check-evidence-file>" >&2
  exit 64
fi

CONTROL_JSON_FILE="$1"
FAILED_CHECKS_FILE="$2"
FAILED_CHECK_EVIDENCE_FILE="$3"

if [ ! -r "$CONTROL_JSON_FILE" ] || [ ! -r "$FAILED_CHECKS_FILE" ] || [ ! -r "$FAILED_CHECK_EVIDENCE_FILE" ]; then
  echo "FAILED_CHECK_EVIDENCE_NOT_REFERENCED"
  echo "Reason: control JSON, failed-check list, or failed-check evidence file is unreadable."
  exit 4
fi

if [ ! -s "$FAILED_CHECKS_FILE" ]; then
  exit 0
fi

review_text="$(
  python3 - "$CONTROL_JSON_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

control = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
parts = [str(control.get("summary") or ""), str(control.get("reason") or "")]
for finding in control.get("findings") or []:
    parts.append(
        "\n".join(
            str(finding.get(field) or "")
            for field in (
                "path",
                "line",
                "severity",
                "title",
                "problem",
                "root_cause",
                "fix_direction",
                "regression_test_direction",
                "suggested_diff",
            )
        )
    )
print("\n".join(parts))
PY
)"

contains_review_text() {
  local needle="$1"
  if [ -z "$needle" ]; then
    return 0
  fi

  local was_nocasematch=0
  if shopt -q nocasematch; then
    was_nocasematch=1
  fi
  shopt -s nocasematch

  local result=1
  if [[ "$review_text" == *"$needle"* ]]; then
    result=0
  fi

  if [ "$was_nocasematch" -eq 0 ]; then
    shopt -u nocasematch
  fi

  return "$result"
}

reject_failed_check_review() {
  echo "FAILED_CHECK_EVIDENCE_NOT_REFERENCED"
  echo "Reason: $1"
  exit 4
}

reject_non_actionable_failed_check_review() {
  local marker

  for marker in \
    "No deterministic missing-string markers" \
    "No deterministic missing string markers" \
    "Strix report locations were recognized" \
    "Use the failed-check evidence below to map" \
    "map each failed check to exact local source lines before approving"
  do
    if contains_review_text "$marker"; then
      reject_failed_check_review "review text punts failed-check diagnosis back to the reader: ${marker}"
    fi
  done
}

extract_strix_required_markers() {
  perl -CS -ne '
    s/\r//g;
    s/\x1b\[[0-9;?]*[A-Za-z]//g;
    if (/│/) {
      s/^.*?│[[:space:]]*//;
      s/[[:space:]]*│.*$//;
    } else {
      s/^.*?[0-9]Z[[:space:]]+//;
    }
    s/[[:space:]]+/ /g;
    s/^[[:space:]]+|[[:space:]]+$//g;

    if (/^Title:[[:space:]]+(.+)/) {
      print "$1\n";
    }
    if (/^Severity:[[:space:]]+(CRITICAL|HIGH|MEDIUM|LOW)\b/) {
      print "Severity: $1\n";
    }
    if (/^Endpoint:[[:space:]]+(.+)/) {
      print "$1\n";
    }
    if (/^Method:[[:space:]]+(.+)/) {
      print "Method: $1\n";
    }
    if (/^Location[[:space:]]+[0-9]+:[[:space:]]+(.+:[0-9]+(?:-[0-9]+)?)/) {
      print "$1\n";
    }
  ' "$FAILED_CHECK_EVIDENCE_FILE"
}

extract_strix_title_markers() {
  perl -CS -ne '
    s/\r//g;
    s/\x1b\[[0-9;?]*[A-Za-z]//g;
    if (/│/) {
      s/^.*?│[[:space:]]*//;
      s/[[:space:]]*│.*$//;
    } else {
      s/^.*?[0-9]Z[[:space:]]+//;
    }
    s/[[:space:]]+/ /g;
    s/^[[:space:]]+|[[:space:]]+$//g;
    if (/^Title:[[:space:]]+(.+)/) {
      print "$1\n";
    }
  ' "$FAILED_CHECK_EVIDENCE_FILE"
}

extract_strix_report_model_markers() {
  perl -CS -ne '
    s/\r//g;
    s/\x1b\[[0-9;?]*[A-Za-z]//g;
    if (/│/) {
      s/^.*?│[[:space:]]*//;
      s/[[:space:]]*│.*$//;
    } else {
      s/^.*?[0-9]Z[[:space:]]+//;
    }
    s/[[:space:]]+/ /g;
    s/^[[:space:]]+|[[:space:]]+$//g;

    if (/^### Strix vulnerability report window/i) {
      $in_window = 1;
      while (m{(?:model|for model)[[:space:]]+((?:github[-_]models|openai|deepseek|vertex_ai)/[A-Za-z0-9._/-]+)}gi) {
        print "$1\n";
      }
      next;
    }
    next unless $in_window;
    if (m{(?:^|[[:space:]])Model[[:space:]]+((?:github[-_]models|openai|deepseek|vertex_ai)/[A-Za-z0-9._/-]+)}i) {
      print "$1\n";
    }
  ' "$FAILED_CHECK_EVIDENCE_FILE" | sort -u
}

count_strix_review_findings() {
  python3 - "$CONTROL_JSON_FILE" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

control = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
pattern = re.compile(
    r"strix|github[-_]models/|deepseek/|openai/gpt-|vertex_ai/|Vulnerability Report",
    re.IGNORECASE,
)
count = 0
for finding in control.get("findings") or []:
    text = "\n".join(
        str(finding.get(field) or "")
        for field in (
            "title",
            "problem",
            "root_cause",
            "fix_direction",
            "regression_test_direction",
            "suggested_diff",
        )
    )
    if pattern.search(text):
        count += 1
print(count)
PY
}

validate_distinct_strix_report_findings() {
  python3 - "$CONTROL_JSON_FILE" "$FAILED_CHECK_EVIDENCE_FILE" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


control_file = Path(sys.argv[1])
evidence_file = Path(sys.argv[2])
control = json.loads(control_file.read_text(encoding="utf-8"))
evidence_text = evidence_file.read_text(encoding="utf-8", errors="replace")

ansi_re = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
model_re = re.compile(
    r"(?:^|[\s])Model\s+((?:github[-_]models|openai|deepseek|vertex_ai)/[A-Za-z0-9._/-]+)",
    re.IGNORECASE,
)
failed_model_re = re.compile(r"Strix run failed for model '([^']+)'")
location_re = re.compile(
    r"(?:Code\s+)?Locations?(?:\s+[0-9]+)?\s*:\s*(.+?:[0-9]+(?:-[0-9]+)?)",
    re.IGNORECASE,
)
clean_prefix_pipe_re = re.compile(r"^.*?│\s*")
clean_suffix_pipe_re = re.compile(r"\s*│.*$")
clean_prefix_z_re = re.compile(r"^.*?[0-9]Z\s+")
clean_whitespace_re = re.compile(r"\s+")
new_field_re = re.compile(r"^(Title|Severity|CVSS Score|CVSS Vector|Target|Endpoint|Method|Description|Impact|Technical Analysis|PoC Description|PoC Code|Code Locations|Remediation)\b", re.IGNORECASE)
window_model_re = re.compile(r"(?:model|for model)\s+((?:github[-_]models|openai|deepseek|vertex_ai)/[A-Za-z0-9._/-]+)", re.IGNORECASE)
continuation_border_re = re.compile(r"^[╭╰─]+$")
field_title_re = re.compile(r"^Title:\s+(.+)", re.IGNORECASE)
field_severity_re = re.compile(r"^Severity:\s+(CRITICAL|HIGH|MEDIUM|LOW|NONE)\b", re.IGNORECASE)
field_endpoint_re = re.compile(r"^Endpoint:\s+(.+)", re.IGNORECASE)
field_method_re = re.compile(r"^Method:\s+(.+)", re.IGNORECASE)
field_target_re = re.compile(r"^Target:\s+(.+)", re.IGNORECASE)


def clean(raw_line: str) -> str:
    line = ansi_re.sub("", raw_line).replace("\r", "")
    if "│" in line:
        line = clean_prefix_pipe_re.sub("", line)
        line = clean_suffix_pipe_re.sub("", line)
    else:
        line = clean_prefix_z_re.sub("", line)
    line = clean_whitespace_re.sub(" ", line).strip()
    return line


def starts_new_field(line: str) -> bool:
    return bool(new_field_re.match(line))


class ReportParser:
    def __init__(self) -> None:
        self.reports: list[dict[str, str]] = []
        self.in_window = False
        self.window_model = ""
        self.current_model = ""
        self.report_model = ""
        self.title = ""
        self.severity = ""
        self.endpoint = ""
        self.method = ""
        self.target = ""
        self.location = ""
        self.continuation = ""

    def finish_report(self) -> None:
        if self.title:
            self.reports.append(
                {
                    "model": self.report_model or self.window_model or self.current_model or "unknown-model",
                    "title": self.title,
                    "severity": self.severity,
                    "endpoint": self.endpoint,
                    "method": self.method,
                    "target": self.target,
                    "location": self.location,
                }
            )
        self.report_model = self.title = self.severity = self.endpoint = self.method = self.target = self.location = ""

    def _handle_window_start(self, line: str) -> bool:
        if not line.lower().startswith("### strix vulnerability report window"):
            return False
        self.finish_report()
        self.in_window = True
        self.window_model = ""
        match = window_model_re.search(line)
        if match:
            self.window_model = match.group(1)
            self.current_model = match.group(1)
        self.continuation = ""
        return True

    def _update_models(self, line: str) -> None:
        match = model_re.search(line) or failed_model_re.search(line)
        if match:
            self.current_model = match.group(1)
            if self.in_window:
                self.window_model = self.current_model
            if self.in_window and self.title:
                self.report_model = self.current_model

    def _handle_continuation(self, line: str) -> bool:
        if not self.continuation:
            return False
        if not line:
            self.continuation = ""
        elif not starts_new_field(line) and not continuation_border_re.match(line) and line.lower() != "vulnerability report":
            if self.continuation == "title":
                self.title = f"{self.title} {line}".strip()
            elif self.continuation == "endpoint":
                self.endpoint = f"{self.endpoint} {line}".strip()
            elif self.continuation == "target":
                self.target = f"{self.target} {line}".strip()
            return True
        else:
            self.continuation = ""
        return False

    def _parse_field(self, line: str) -> None:
        field_match = field_title_re.match(line)
        if field_match:
            self.finish_report()
            self.title = field_match.group(1)
            self.report_model = self.window_model
            self.continuation = "title"
            return
        field_match = field_severity_re.match(line)
        if field_match:
            self.severity = field_match.group(1).upper()
            return
        field_match = field_endpoint_re.match(line)
        if field_match:
            self.endpoint = field_match.group(1)
            self.continuation = "endpoint"
            return
        field_match = field_method_re.match(line)
        if field_match:
            self.method = field_match.group(1)
            self.continuation = ""
            return
        field_match = field_target_re.match(line)
        if field_match:
            self.target = field_match.group(1)
            self.continuation = "target"
            return
        field_match = location_re.search(line)
        if field_match and not self.location:
            self.location = field_match.group(1)

    def process_line(self, line: str) -> None:
        if self._handle_window_start(line):
            return

        self._update_models(line)

        if not self.in_window:
            return

        if self._handle_continuation(line):
            return

        if line.lower() == "vulnerability report":
            return

        self._parse_field(line)


def parse_reports(text: str) -> list[dict[str, str]]:
    parser = ReportParser()
    for raw_line in text.splitlines():
        parser.process_line(clean(raw_line))
    parser.finish_report()
    return [report for report in parser.reports if report["title"] and report["severity"] != "NONE"]


def finding_text(finding: dict[str, object]) -> str:
    fields = [
        "path",
        "line",
        "severity",
        "title",
        "problem",
        "root_cause",
        "fix_direction",
        "regression_test_direction",
        "suggested_diff",
    ]
    return "\n".join(str(finding.get(field, "")) for field in fields).lower()


def contains(text: str, marker: str) -> bool:
    return not marker or marker.lower() in text


reports = parse_reports(evidence_text)
if not reports:
    raise SystemExit(0)

findings = [finding_text(finding) for finding in control.get("findings", []) if isinstance(finding, dict)]
used_findings: set[int] = set()

for report in reports:
    required_markers = [
        report["model"],
        report["title"],
        report["severity"],
        report["endpoint"],
        report["method"],
        report["location"],
    ]
    for index, text in enumerate(findings):
        if index in used_findings:
            continue
        if all(contains(text, marker) for marker in required_markers):
            used_findings.add(index)
            break
    else:
        raise SystemExit(1)
PY
}

reject_non_actionable_failed_check_review

while IFS= read -r failed_check_line; do
  case "$failed_check_line" in
    "- "*)
      failed_check_label="${failed_check_line#- }"
      failed_check_label="${failed_check_label%%:*}"
      if ! contains_review_text "$failed_check_label"; then
        reject_failed_check_review "review does not name failed check '${failed_check_label}'."
      fi
      ;;
  esac
done <"$FAILED_CHECKS_FILE"

while IFS= read -r fail_marker; do
  if ! contains_review_text "$fail_marker"; then
    reject_failed_check_review "review does not cite failed-log marker '${fail_marker}'."
  fi
done < <(awk -F 'FAIL: ' 'NF > 1 { print $2 }' "$FAILED_CHECK_EVIDENCE_FILE" | sort -u)

for evidence_marker in \
  "Self-test Strix gate script" \
  "github.event.client_payload.strix_llm" \
  "STRIX_LLM must select" \
  "MODEL: nvidia-nim/nvidia/llama-3.3-nemotron-super-49b-v1.5"
do
  if grep -Fq -- "$evidence_marker" "$FAILED_CHECK_EVIDENCE_FILE" &&
    ! contains_review_text "$evidence_marker"; then
    reject_failed_check_review "review omits required evidence marker '${evidence_marker}'."
  fi
done

if grep -Fq "Strix vulnerability report window" "$FAILED_CHECK_EVIDENCE_FILE"; then
  if ! validate_distinct_strix_report_findings; then
    reject_failed_check_review "Strix vulnerability reports were not mapped to distinct source-backed findings."
  fi

  strix_title_count="$(extract_strix_title_markers | sed '/^[[:space:]]*$/d' | wc -l | tr -d '[:space:]')"
  finding_count="$(count_strix_review_findings)"
  if [ -n "$strix_title_count" ] && [ "$strix_title_count" -gt 0 ] &&
    [ "$finding_count" -lt "$strix_title_count" ]; then
    reject_failed_check_review "review has fewer Strix-specific findings (${finding_count}) than Strix report titles (${strix_title_count})."
  fi

  while IFS= read -r model_name; do
    if ! contains_review_text "$model_name"; then
      reject_failed_check_review "review omits Strix report model '${model_name}'."
    fi
  done < <(extract_strix_report_model_markers)

  while IFS= read -r strix_marker; do
    if ! contains_review_text "$strix_marker"; then
      reject_failed_check_review "review omits Strix report marker '${strix_marker}'."
    fi
  done < <(extract_strix_required_markers)
fi

exit 0
