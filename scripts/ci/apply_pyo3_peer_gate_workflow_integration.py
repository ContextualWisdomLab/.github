#!/usr/bin/env python3
"""Apply the reviewed PR #789 workflow integration and remove this script."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"
AGENT_TEST = ROOT / "tests/test_opencode_agent_contract.py"
HELPER_TEST = ROOT / "tests/test_python_native_extension_peer_gate.py"
DOCTORING = ROOT / "docs/doctoring/python-native-extension-peer-evidence.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Return text with one reviewed replacement or fail closed."""

    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one {label} replacement")
    return text.replace(old, new, 1)


def update_workflow() -> None:
    """Wire bounded PyO3 classification and exact-head peer checks."""

    text = WORKFLOW.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "          failures=0\n          r_peer_check_required=0\n",
        "          failures=0\n"
        "          python_native_peer_check_required=0\n"
        "          r_peer_check_required=0\n",
        "coverage state",
    )

    runner = r'''          run_python_native_extension_classifier() {
            local python_native_pytest_log="$1"
            local project_dir="$2"
            local python_native_changed_files="$3"
            local expected_pyproject_sha="$4"
            local pyproject_file="$project_dir/pyproject.toml"

            [ -n "$expected_pyproject_sha" ] \
              && [ -f "$pyproject_file" ] \
              && [ ! -L "$pyproject_file" ] \
              && [ "$(sha256sum "$pyproject_file" | awk '{print $1}')" = "$expected_pyproject_sha" ] \
              && python3 -I "$GITHUB_WORKSPACE/scripts/ci/python_native_extension_peer_gate.py" \
                classify-pytest \
                --log "$python_native_pytest_log" \
                --repo-root "$COVERAGE_SOURCE_WORKDIR" \
                --pyproject "$project_dir/pyproject.toml" \
                --changed-files "$python_native_changed_files"
          }

          run_python_test_and_capture() {
            local label="$1"
            local project_dir="$2"
            shift 2
            local log_file changed_file pyproject_file pyproject_sha classification rc
            log_file="$(mktemp)"
            changed_file="$(mktemp)"
            pyproject_file="$project_dir/pyproject.toml"
            pyproject_sha=""
            changed_files_for_coverage >"$changed_file"
            if [ -f "$pyproject_file" ] && [ ! -L "$pyproject_file" ]; then
              pyproject_sha="$(sha256sum "$pyproject_file" | awk '{print $1}')"
            fi

            append "### ${label}"
            append ""
            append '```text'
            append_command "$@"
            set +e
            timeout --kill-after=20 900 setpriv \
              --reuid "$OPENCODE_SANDBOX_UID" \
              --regid "$OPENCODE_SANDBOX_GID" \
              --clear-groups \
              env \
              -u ACTIONS_ID_TOKEN_REQUEST_TOKEN \
              -u ACTIONS_ID_TOKEN_REQUEST_URL \
              -u ACTIONS_RUNTIME_TOKEN \
              -u GH_TOKEN \
              -u GITHUB_TOKEN \
              GITHUB_ENV=/dev/null \
              GITHUB_PATH=/dev/null \
              GITHUB_OUTPUT=/dev/null \
              GITHUB_STEP_SUMMARY=/dev/null \
              BASH_ENV=/dev/null \
              UV_NO_BUILD=1 \
              GIT_CONFIG_NOSYSTEM=1 \
              GIT_CONFIG_GLOBAL=/dev/null \
              GIT_CONFIG_COUNT=1 \
              GIT_CONFIG_KEY_0=safe.directory \
              GIT_CONFIG_VALUE_0=/work \
              HOME=/work/.opencode-sandbox-home \
              XDG_CACHE_HOME=/work/.opencode-sandbox-cache \
              CARGO_HOME=/work/.opencode-sandbox-home/.cargo \
              PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
              "$@" >"$log_file" 2>&1
            rc=$?
            set -e
            emit_captured_log "$log_file"
            append '```'
            append ""

            if [ "$rc" -eq 0 ]; then
              append "- Result: PASS"
            else
              classification_file="$(mktemp)"
              if run_python_native_extension_classifier \
                "$log_file" \
                "$project_dir" \
                "$changed_file" \
                "$pyproject_sha" >"$classification_file" 2>/dev/null; then
                classification="$(cat "$classification_file")"
                append "- Result: DEFERRED"
                append ""
                append "### Python native-extension source-only deferral"
                append ""
                append "- Result: DEFERRED"
                append "- Reason: the unchanged declared PyO3 module was unavailable in the source-only sandbox; exact-head Python, Rust/PyO3, and package CheckRuns are required before approval."
                python_native_peer_check_required=1
                printf 'Deferred source-only Python collection after bounded classification: %s\n' "$classification"
              else
                append "- Result: FAIL (exit ${rc})"
                failures=$((failures + 1))
              fi
              rm -f "$classification_file"
            fi
            append ""
            rm -f "$log_file" "$changed_file"
          }

'''
    text = replace_once(
        text,
        "          run_r_package_testthat() {\n",
        runner + "          run_r_package_testthat() {\n",
        "Python runner insertion",
    )
    text = replace_once(
        text,
        "                  run_and_capture \"Python configured CI test suite (${project_dir})\" \\\n"
        "                    python3 \"${GITHUB_WORKSPACE}/scripts/ci/safe_pytest_command.py\" execute \\\n"
        "                      --project-dir \"$project_dir\" \\\n"
        "                      --command-json \"$configured_command_json\"\n",
        "                  run_python_test_and_capture \"Python configured CI test suite (${project_dir})\" \"$project_dir\" \\\n"
        "                    python3 \"${GITHUB_WORKSPACE}/scripts/ci/safe_pytest_command.py\" execute \\\n"
        "                      --project-dir \"$project_dir\" \\\n"
        "                      --command-json \"$configured_command_json\"\n",
        "configured Python command",
    )
    text = replace_once(
        text,
        "              run_and_capture \"Python coverage with missing-line report (${project_dir})\" \\\n"
        "                bash -c 'cd \"$1\" && PYTHONPATH=\"$([ -d src ] && printf src:. || printf .)\" python3 -m coverage run -m pytest tests && python3 -m coverage report --show-missing' bash \"$project_dir\"\n",
        "              run_python_test_and_capture \"Python coverage with missing-line report (${project_dir})\" \"$project_dir\" \\\n"
        "                bash -c 'cd \"$1\" && PYTHONPATH=\"$([ -d src ] && printf src:. || printf .)\" python3 -m coverage run -m pytest tests && python3 -m coverage report --show-missing' bash \"$project_dir\"\n",
        "project Python command",
    )
    text = replace_once(
        text,
        "                run_and_capture \"Python coverage with missing-line report\" \\\n"
        "                  bash -c 'PYTHONPATH=\"$([ -d src ] && printf src:. || printf .)\" python3 -m coverage run -m pytest && python3 -m coverage report --show-missing'\n",
        "                run_python_test_and_capture \"Python coverage with missing-line report\" \".\" \\\n"
        "                  bash -c 'PYTHONPATH=\"$([ -d src ] && printf src:. || printf .)\" python3 -m coverage run -m pytest && python3 -m coverage report --show-missing'\n",
        "root Python command",
    )
    text = replace_once(
        text,
        "                run_and_capture \"Python pytest-cov coverage\" python3 -m pytest --cov=. --cov-report=term-missing\n",
        "                run_python_test_and_capture \"Python pytest-cov coverage\" \".\" python3 -m pytest --cov=. --cov-report=term-missing\n",
        "pytest-cov command",
    )
    text = replace_once(
        text,
        "          if [ \"$failures\" -eq 0 ]; then\n"
        "            append \"- Result: PASS\"\n",
        "          if [ \"$failures\" -eq 0 ]; then\n"
        "            if [ \"$python_native_peer_check_required\" -eq 1 ] || [ \"$r_peer_check_required\" -eq 1 ]; then\n"
        "              append \"- Result: DEFERRED\"\n"
        "            else\n"
        "              append \"- Result: PASS\"\n"
        "            fi\n",
        "coverage decision",
    )
    text = replace_once(
        text,
        "              if [ \"$r_peer_check_required\" -eq 1 ]; then\n"
        "                append \"- R test evidence: deferred package-load failures require a successful current-head peer R CMD check\"\n"
        "              fi\n",
        "              if [ \"$python_native_peer_check_required\" -eq 1 ]; then\n"
        "                append \"- Python native-extension peer evidence: deferred source-only collection requires successful exact-head peer checks\"\n"
        "              fi\n"
        "              if [ \"$r_peer_check_required\" -eq 1 ]; then\n"
        "                append \"- R test evidence: deferred package-load failures require a successful current-head peer R CMD check\"\n"
        "              fi\n",
        "coverage peer markers",
    )

    peer_functions = r'''          coverage_defers_to_python_native_checks() {
            printf '%s\n' "${COVERAGE_EVIDENCE_SUMMARY:-}" |
              grep -Fq -- "- Python native-extension peer evidence: deferred source-only collection requires successful exact-head peer checks"
          }

          collect_python_native_check_runs() {
            local output_file="$1"
            local raw_file owner repository_name
            owner="${GH_REPOSITORY%%/*}"
            repository_name="${GH_REPOSITORY#*/}"
            raw_file="$(mktemp)"
            if ! gh api graphql \
              -f query='query($owner:String!, $repository:String!, $number:Int!) {
                repository(owner:$owner, name:$repository) {
                  pullRequest(number:$number) {
                    headRefOid
                    commits(last:1) {
                      nodes {
                        commit {
                          oid
                          statusCheckRollup {
                            contexts(first:100) {
                              nodes {
                                __typename
                                ... on CheckRun {
                                  name
                                  status
                                  conclusion
                                  checkSuite {
                                    workflowRun {
                                      workflow { name }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }' \
              -f owner="$owner" \
              -f repository="$repository_name" \
              -F number="$PR_NUMBER" >"$raw_file"; then
              rm -f "$raw_file"
              return 1
            fi
            if ! jq --arg head "$PR_HEAD_SHA" '
              .data.repository.pullRequest as $pr
              | if ($pr.headRefOid // "") != $head then error("stale pull-request head") else . end
              | [
                  $pr.commits.nodes[-1].commit.statusCheckRollup.contexts.nodes[]?
                  | select(.__typename == "CheckRun")
                  | {
                      __typename,
                      name,
                      status,
                      conclusion,
                      head_sha: $head,
                      checkSuite
                    }
                ]
            ' "$raw_file" >"$output_file"; then
              rm -f "$raw_file"
              return 1
            fi
            rm -f "$raw_file"
          }

          require_python_native_checks_for_deferred_coverage() {
            local python_native_peer_check_required=0
            local check_runs_file
            if coverage_defers_to_python_native_checks; then
              python_native_peer_check_required=1
            fi
            if [ "$python_native_peer_check_required" -eq 0 ]; then
              return 0
            fi

            check_runs_file="$(mktemp "${RUNNER_TEMP}/python-native-check-runs.XXXXXX.json")"
            if collect_github_checks_with_retry \
              collect_python_native_check_runs "$check_runs_file" \
              && python3 "$GITHUB_WORKSPACE/scripts/ci/python_native_extension_peer_gate.py" \
                require-checks \
                --checks-json "$check_runs_file" \
                --head-sha "$PR_HEAD_SHA" \
                --required-check "CI::python" \
                --required-check "CI::rust" \
                --required-check "CI::package" >/dev/null; then
              rm -f "$check_runs_file"
              printf 'Verified exact-head Python, Rust/PyO3, and package CheckRun evidence after source-only PyO3 deferral.\n'
              return 0
            fi
            rm -f "$check_runs_file"
            printf '::notice::Python native-extension source-only deferral cannot authorize approval without successful exact-head Python, Rust/PyO3, and package CheckRuns.\n'
            return 1
          }

'''
    r_marker = (
        "          collect_successful_r_cmd_check_evidence() {\n"
    )
    text = replace_once(text, r_marker, peer_functions + r_marker, "peer functions")
    text = replace_once(
        text,
        "            if ! require_r_cmd_check_for_deferred_coverage; then\n"
        "              return 1\n"
        "            fi\n",
        "            if ! require_python_native_checks_for_deferred_coverage; then\n"
        "              return 1\n"
        "            fi\n"
        "            if ! require_r_cmd_check_for_deferred_coverage; then\n"
        "              return 1\n"
        "            fi\n",
        "fallback peer gate",
    )
    normal = """              if ! require_r_cmd_check_for_deferred_coverage; then
                body="$(printf '%s\\n' \\
"""
    python_hold = """              if ! require_python_native_checks_for_deferred_coverage; then
                body="$(printf '%s\\n' \\
                  "## Pull request overview" \\
                  "" \\
                  "OpenCode reviewed the current-head source evidence but Python collection was deferred after a bounded missing-PyO3 classification." \\
                  "" \\
                  "## Approval hold" \\
                  "" \\
                  "### Successful exact-head Python, Rust/PyO3, and package CheckRuns are required" \\
                  "- Problem: coverage-evidence deferred a source-only missing-extension collection failure, but the required exact-head peer CheckRuns were not proven." \\
                  "- Root cause: the isolated source sandbox does not build PR-selected native code; deferral is safe only when the repository's trusted jobs built and tested the unchanged extension on this exact head." \\
                  "- Fix: repair or rerun the current-head CI Python, Rust/PyO3, and package jobs, then rerun OpenCode." \\
                  "- Regression test: Keep PyO3 source-only deferral fail-closed unless live GraphQL CheckRun evidence proves CI::python, CI::rust, and CI::package at the exact head." \\
                  "" \\
                  "- Result: WAITING_FOR_PYTHON_NATIVE_PEER_CHECKS" \\
                  "- Head SHA: \\`${HEAD_SHA}\\`" \\
                  "- Workflow run: ${RUN_ID}" \\
                  "- Workflow attempt: ${RUN_ATTEMPT}"
                )"
                hold_approval_without_review "WAITING_FOR_PYTHON_NATIVE_PEER_CHECKS" "$body"
              fi
""" + normal
    text = replace_once(text, normal, python_hold, "normal peer hold")
    WORKFLOW.write_text(text, encoding="utf-8")


def update_tests_and_docs() -> None:
    """Update permanent workflow contracts, coverage, and operator records."""

    text = AGENT_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    assert measure_step.count("GIT_CONFIG_COUNT=1") == 3\n'
        '    assert measure_step.count("GIT_CONFIG_KEY_0=safe.directory") == 3\n'
        '    assert measure_step.count("GIT_CONFIG_VALUE_0=/work") == 3\n',
        '    # Generic, advisory, R, and Python-native-aware runners must all keep the\n'
        '    # same isolated Git trust boundary.\n'
        '    assert measure_step.count("GIT_CONFIG_COUNT=1") == 4\n'
        '    assert measure_step.count("GIT_CONFIG_KEY_0=safe.directory") == 4\n'
        '    assert measure_step.count("GIT_CONFIG_VALUE_0=/work") == 4\n',
        "Git boundary count",
    )
    text = replace_once(
        text,
        '    assert measure.count("GITHUB_ENV=/dev/null") == 3\n'
        '    assert measure.count("GITHUB_PATH=/dev/null") == 3\n'
        '    assert measure.count("GITHUB_OUTPUT=/dev/null") == 3\n'
        '    assert measure.count("GITHUB_STEP_SUMMARY=/dev/null") == 3\n'
        '    assert measure.count("BASH_ENV=/dev/null") == 3\n',
        '    # Generic, advisory, R, and Python-native-aware untrusted commands all\n'
        '    # receive the same non-publication environment.\n'
        '    assert measure.count("GITHUB_ENV=/dev/null") == 4\n'
        '    assert measure.count("GITHUB_PATH=/dev/null") == 4\n'
        '    assert measure.count("GITHUB_OUTPUT=/dev/null") == 4\n'
        '    assert measure.count("GITHUB_STEP_SUMMARY=/dev/null") == 4\n'
        '    assert measure.count("BASH_ENV=/dev/null") == 4\n',
        "publication boundary count",
    )
    AGENT_TEST.write_text(text, encoding="utf-8")

    text = HELPER_TEST.read_text(encoding="utf-8")
    addition = '''


def test_repository_contract_rejects_resolved_pyproject_outside_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path-resolution race cannot rebind the project metadata outside its root."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    pyproject = write(project_root / "pyproject.toml", PYPROJECT)
    original_resolve = Path.resolve

    def redirected_resolve(path: Path, *args, **kwargs):
        if path == pyproject:
            return tmp_path / "outside" / "pyproject.toml"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    assert gate._repository_contract_paths(
        repo_root_path=tmp_path,
        pyproject_path=pyproject,
        manifest_path=PurePosixPath("crates/fast-mlsirm-py/Cargo.toml"),
        python_source=PurePosixPath("python"),
    ) is None
'''
    if "test_repository_contract_rejects_resolved_pyproject_outside_project" not in text:
        text += addition
    HELPER_TEST.write_text(text, encoding="utf-8")

    text = DOCTORING.read_text(encoding="utf-8")
    marker = "## Exact-head peer evidence\n"
    section = '''## Central workflow integration

The protected central coverage workflow records each Python test command in a
bounded log and preserves its exit status. Ordinary passing commands remain
PASS. A failing Python command is considered for deferral only after the exact
base-to-head changed-file list and the unchanged regular ``pyproject.toml`` have
been validated by the published classifier. Successful classification produces
a distinct ``DEFERRED`` section and never ordinary passing evidence.

The trusted approval phase independently queries the live pull request head with
GitHub GraphQL, retains the ``CheckRun`` type and nested workflow identity, and
normalizes those records for ``require-checks``. For the current ``fast-mlsirm``
contract, ``CI::python``, ``CI::rust``, and ``CI::package`` must all be completed
and successful on the exact head. Missing, stale, pending, failed, status-only,
or lookalike evidence prevents approval. The existing R package-load deferral
remains an independent gate.

'''
    if section not in text:
        text = replace_once(text, marker, section + marker, "doctoring section")
    text = text.replace(
        "Local verification before publication reported 81 tests passing with 220/220\n"
        "production statements and 98/98 production branches covered. Permanent central\n",
        "Focused integration verification after wiring the protected workflow reported 91\n"
        "tests passing. Permanent quality CI remains authoritative for 220/220 production\n"
        "statements, 98/98 production branches, Python 3.10/3.14 compatibility, workflow\n"
        "syntax, and the complete central suite. Permanent central\n",
    )
    DOCTORING.write_text(text, encoding="utf-8")

    text = CHANGELOG.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "- Added a bounded PyO3/maturin pytest-failure classifier and exact-head native peer-check verifier so source-only OpenCode sandboxes can distinguish one unchanged-extension collection limitation from product failures without skipping tests, executing pull-request build hooks, or weakening Rust ownership.",
        "- Added and integrated a bounded PyO3/maturin pytest-failure classifier and exact-head native peer-check verifier so source-only OpenCode sandboxes emit distinct deferred evidence only for one unchanged-extension collection limitation, while approval still requires live successful `CI::python`, `CI::rust`, and `CI::package` CheckRuns on the exact head without skipping tests, executing pull-request build hooks, or weakening Rust ownership.",
        "changelog entry",
    )
    CHANGELOG.write_text(text, encoding="utf-8")


def cleanup_temporary_files() -> None:
    """Remove temporary migration and duplicate snapshot workflows."""

    for path in (
        ROOT / ".github/workflows/dev-source-snapshot.yml",
        ROOT / ".github/workflows/python-native-extension-peer-gate-quality.yml",
    ):
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    update_workflow()
    update_tests_and_docs()
    cleanup_temporary_files()
    print("Applied PR #789 central PyO3 peer-gate integration.")
