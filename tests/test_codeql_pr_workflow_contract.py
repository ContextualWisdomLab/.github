import json
import os
import re
from pathlib import Path
import subprocess
import sys
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_codeql_pr_workflow_gates_head_and_merge_sarif_locally() -> None:
    workflow = (REPO_ROOT / ".github/workflows/codeql-pr.yml").read_text(
        encoding="utf-8"
    )

    assert "name: CodeQL PR" in workflow
    assert "branches: [main, master, develop]" in workflow
    assert workflow.count("upload: false") == 2
    assert "upload: always" not in workflow
    assert workflow.count("Enforce CodeQL Medium+ SARIF gate") == 2
    assert workflow.count("CODEQL_FINDING rule=") == 2
    assert workflow.count("Preserve CodeQL SARIF evidence") == 2
    assert "security-severity" in workflow
    assert "score >= 4.0" in workflow
    assert "result.get(\"suppressions\")" in workflow
    assert "detect-languages:" in workflow
    assert "java-kotlin" in workflow
    assert "-name '*.java'" in workflow
    assert "-name '*.kt'" in workflow
    assert "analyze-head:" in workflow
    assert "analyze-merge:" in workflow
    assert "merge_commit_sha != ''" in workflow
    assert "CodeQL merge preview" in workflow
    assert workflow.count("Retry Initialize CodeQL after GitHub API outage") == 2
    assert workflow.count("No server is currently available") == 2
    assert workflow.count("id: init-codeql") == 2
    assert "github.event.pull_request.head.sha" in workflow
    assert "github.event.pull_request.merge_commit_sha" in workflow
    assert "refs/pull/{0}/head" in workflow
    assert "refs/pull/{0}/merge" in workflow
    assert workflow.count("security-events: read") == 2
    assert "security-events: write" not in workflow


def test_codeql_action_steps_use_one_version_per_workflow() -> None:
    """Prevent CodeQL init/analyze version splits from failing PR analysis."""
    for filename in ("codeql-pr.yml", "scheduled-security-scan.yml"):
        workflow = (REPO_ROOT / ".github/workflows" / filename).read_text(
            encoding="utf-8"
        )
        refs = set(
            re.findall(
                r"github/codeql-action/(?:init|analyze|upload-sarif)@([0-9a-f]{40})",
                workflow,
            )
        )

        assert len(refs) == 1, f"{filename} mixes CodeQL action refs: {sorted(refs)}"


def test_codeql_sarif_gate_logs_and_fails_only_unsuppressed_medium_plus(
    tmp_path: Path,
) -> None:
    workflow = (REPO_ROOT / ".github/workflows/codeql-pr.yml").read_text(
        encoding="utf-8"
    )
    marker = "      - name: Enforce CodeQL Medium+ SARIF gate\n"
    start = workflow.index(marker)
    run_start = workflow.index("        run: |\n", start) + len("        run: |\n")
    run_end = workflow.index("\n      - name:", run_start)
    script = textwrap.dedent(
        "\n".join(line[10:] for line in workflow[run_start:run_end].splitlines())
    )

    sarif_dir = tmp_path / "codeql-results-head"
    sarif_dir.mkdir()
    sarif_path = sarif_dir / "python.sarif"
    rule = {
        "id": "py/example",
        "properties": {"tags": ["security", "external/cwe/cwe-089"]},
        "defaultConfiguration": {"level": "warning"},
    }
    sarif_path.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "tool": {"driver": {"rules": [rule]}},
                        "results": [
                            {
                                "ruleId": "py/example",
                                "properties": {"security-severity": "7.5"},
                                "message": {"text": "medium issue\nwith detail"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": "app.py"},
                                            "region": {"startLine": 9},
                                        }
                                    }
                                ],
                            },
                            {
                                "ruleId": "py/example",
                                "properties": {"security-severity": "9.1"},
                                "suppressions": [{"kind": "inSource"}],
                                "message": {"text": "suppressed"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "CODEQL_SARIF_DIR": str(sarif_dir)}
    blocked = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert blocked.returncode == 1
    assert "medium_plus=1" in blocked.stdout
    assert (
        "CODEQL_FINDING rule=py/example security-severity=7.5 path=app.py "
        "line=9 message=medium issue with detail" in blocked.stdout
    )
    assert "suppressed" not in blocked.stdout

    payload = json.loads(sarif_path.read_text(encoding="utf-8"))
    payload["runs"][0]["results"] = [
        {
            "ruleId": "py/example",
            "properties": {"security-severity": "3.9"},
            "message": {"text": "low issue"},
        }
    ]
    sarif_path.write_text(json.dumps(payload), encoding="utf-8")
    clean = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert clean.returncode == 0
    assert "medium_plus=0" in clean.stdout
