import io
import hashlib
import json
import runpy
import sys

import pytest

from scripts.ci import adversarial_evidence
from scripts.ci import opencode_existing_approval_gate as gate
from scripts.ci import opencode_review_normalize_output


HEAD = "a" * 40
SOURCE_LINES = (
    b"name: Required OpenCode Review",
    b"on:",
)


def test_standalone_import_path_loads_both_top_level_helpers(monkeypatch):
    """Direct-script imports load both trusted adversarial helper modules."""
    monkeypatch.setitem(sys.modules, "adversarial_evidence", adversarial_evidence)
    monkeypatch.setitem(
        sys.modules,
        "opencode_review_normalize_output",
        opencode_review_normalize_output,
    )
    namespace = runpy.run_path("scripts/ci/opencode_existing_approval_gate.py")
    assert namespace["adversarial_validation_error"] is (
        opencode_review_normalize_output.adversarial_validation_error
    )


@pytest.fixture(autouse=True)
def trusted_adversarial_artifacts(tmp_path, monkeypatch):
    """Provide sealed current-head source and changed-file evidence to the gate."""
    runner_temp = tmp_path / "runner-temp"
    source_root = tmp_path / "source"
    source_path = source_root / ".github" / "workflows" / "opencode-review.yml"
    runner_temp.mkdir()
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"\n".join(SOURCE_LINES) + b"\n")

    changed_files = runner_temp / "opencode-changed-files.txt"
    changed_files.write_text(
        ".github/workflows/opencode-review.yml\n",
        encoding="utf-8",
    )
    manifest = runner_temp / "opencode-artifact-manifest.json"
    changed_files.chmod(0o644)
    manifest.touch(mode=0o644)
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "artifacts": {
                    changed_files.name: hashlib.sha256(
                        changed_files.read_bytes()
                    ).hexdigest()
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(source_root))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    monkeypatch.setenv(
        "OPENCODE_ARTIFACT_MANIFEST_SHA256",
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )


def valid_body(head: str = HEAD) -> str:
    """Build a real-model review body with structured adversarial evidence."""
    evidence = {
        "status": "passed",
        "probes": [
            {
                "path": ".github/workflows/opencode-review.yml",
                "line": line,
                "hypothesis": f"Approval bypass hypothesis {line}.",
                "attack_or_counterexample": f"Supply forged evidence variant {line}.",
                "evidence": (
                    f"Source trace at .github/workflows/opencode-review.yml:{line} "
                    "confirmed the gate rejected the forged evidence. "
                    "source-line-sha256="
                    + hashlib.sha256(source_line).hexdigest()
                ),
                "outcome": "falsified",
            }
            for line, source_line in enumerate(SOURCE_LINES, start=1)
        ],
        "residual_risk": "Hosted token permissions remain externally enforced.",
    }
    return "\n".join(
        (
            "## Pull request overview",
            "",
            gate.PRIMARY_APPROVAL_MARKER,
            "",
            "## Adversarial validation",
            "",
            "```json",
            json.dumps(evidence),
            "```",
            "",
            "- Result: APPROVE",
            f"- Head SHA: `{head}`",
            "- Workflow run: 123",
            "- Workflow attempt: 2",
        )
    )


def review(**overrides):
    """Build a minimal REST review object for approval-gate tests."""
    value = {
        "id": 7,
        "state": "APPROVED",
        "commit_id": HEAD,
        "user": {"login": "opencode-agent[bot]"},
        "body": valid_body(),
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("payload", [[review()], [[review()]]])
def test_flatten_reviews_and_accept_real_model_approval(payload):
    reviews = gate.flatten_reviews(payload)
    log = io.StringIO()
    assert gate.has_reusable_real_model_approval(reviews, HEAD, log=log)
    assert "accepted real-model review" in log.getvalue()


@pytest.mark.parametrize("payload", [{}, ["bad"], [["bad"]]])
def test_flatten_reviews_rejects_malformed_payload(payload):
    with pytest.raises(ValueError):
        gate.flatten_reviews(payload)


def test_extract_adversarial_evidence_uses_last_parseable_block():
    body = "## Adversarial validation\n```json\nnot-json\n```\n" + valid_body()
    assert gate.extract_adversarial_evidence(body)["status"] == "passed"
    assert gate.extract_adversarial_evidence("none") is None


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda value: value.update(state="COMMENTED"), "state"),
        (lambda value: value.update(commit_id="b" * 40), "commit"),
        (lambda value: value.update(user={"login": "unknown"}), "author"),
        (
            lambda value: value.update(
                body=value["body"] + "\ndeterministic fallback approval"
            ),
            "fallback",
        ),
        (
            lambda value: value.update(
                body=value["body"].replace(gate.PRIMARY_APPROVAL_MARKER, "missing")
            ),
            "real-model approval marker",
        ),
        (
            lambda value: value.update(
                body=value["body"].replace("- Result: APPROVE", "")
            ),
            "APPROVE result",
        ),
        (
            lambda value: value.update(
                body=value["body"].replace(f"- Head SHA: `{HEAD}`", "")
            ),
            "current-head",
        ),
        (
            lambda value: value.update(
                body=value["body"].replace("- Workflow run: 123", "")
            ),
            "workflow run",
        ),
        (
            lambda value: value.update(
                body=value["body"].replace("- Workflow attempt: 2", "")
            ),
            "workflow attempt",
        ),
        (
            lambda value: value.update(
                body=value["body"].replace("```json", "```text")
            ),
            "parseable adversarial",
        ),
    ],
)
def test_review_rejection_reason_rejects_non_model_evidence(mutate, reason):
    value = review()
    mutate(value)
    assert reason in gate.review_rejection_reason(value, HEAD)


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        ({"status": "failed", "probes": [{}], "residual_risk": "risk"}, "status"),
        (
            {"status": "passed", "probes": [], "residual_risk": "risk"},
            "probes are empty",
        ),
        (
            {"status": "passed", "probes": ["bad"], "residual_risk": "risk"},
            "not an object",
        ),
        (
            {
                "status": "passed",
                "probes": [
                    {
                        "path": "file",
                        "line": 0,
                        "hypothesis": "hypothesis",
                        "attack_or_counterexample": "attack",
                        "evidence": "evidence",
                        "outcome": "falsified",
                    }
                ],
                "residual_risk": "risk",
            },
            "positive integer",
        ),
        (
            {
                "status": "passed",
                "probes": [
                    {
                        "path": "file",
                        "line": 1,
                        "hypothesis": "hypothesis",
                        "attack_or_counterexample": "attack",
                        "evidence": "evidence",
                    }
                ],
                "residual_risk": "risk",
            },
            "missing outcome",
        ),
        (
            {
                "status": "passed",
                "probes": [
                    {
                        "path": "file",
                        "line": 1,
                        "hypothesis": "hypothesis",
                        "attack_or_counterexample": "attack",
                        "evidence": "evidence",
                        "outcome": "confirmed",
                    }
                ],
                "residual_risk": "risk",
            },
            "not falsified",
        ),
        (
            {
                "status": "passed",
                "probes": [
                    {
                        "path": "file",
                        "line": 1,
                        "hypothesis": "hypothesis",
                        "attack_or_counterexample": "attack",
                        "evidence": "evidence",
                        "outcome": "falsified",
                    }
                ],
                "residual_risk": "",
            },
            "residual_risk",
        ),
    ],
)
def test_adversarial_rejection_reason_explains_invalid_evidence(evidence, reason):
    body = f"## Adversarial validation\n```json\n{json.dumps(evidence)}\n```"
    assert reason in gate.adversarial_rejection_reason(body)


def test_has_reusable_real_model_approval_logs_rejected_candidates():
    fallback = review(body=valid_body() + "\nmodel-unavailable evidence fallback")
    log = io.StringIO()
    assert not gate.has_reusable_real_model_approval(
        [
            review(state="COMMENTED"),
            review(commit_id="b" * 40),
            review(user={"login": "unknown"}),
            fallback,
        ],
        HEAD,
        log=log,
    )
    assert "rejected same-head review" in log.getvalue()
    assert "same-head candidates=1" in log.getvalue()


def test_opencode_app_only_mode_rejects_github_actions_approval():
    actions_review = review(user={"login": "github-actions[bot]"})
    default_log = io.StringIO()
    strict_log = io.StringIO()

    assert not gate.has_reusable_real_model_approval(
        [actions_review], HEAD, log=default_log
    )
    assert not gate.has_reusable_real_model_approval(
        [actions_review],
        HEAD,
        log=strict_log,
        approval_authors=gate.OPENCODE_APP_APPROVAL_AUTHORS,
    )
    assert "not an allowed OpenCode publication actor" in strict_log.getvalue()
    assert "not an allowed OpenCode publication actor" in default_log.getvalue()


def test_opencode_app_only_mode_accepts_app_approval():
    log = io.StringIO()

    assert gate.has_reusable_real_model_approval(
        [review()],
        HEAD,
        log=log,
        approval_authors=gate.OPENCODE_APP_APPROVAL_AUTHORS,
    )
    assert "author=opencode-agent[bot]" in log.getvalue()


def test_adversarial_validation_rejects_circular_or_unanchored_evidence():
    weak = {
        "status": "passed",
        "probes": [
            {
                "path": ".github/workflows/opencode-review.yml",
                "line": 1,
                "hypothesis": "The retry can race.",
                "attack_or_counterexample": "Delay the review API.",
                "evidence": "The retry logic handles this case.",
                "outcome": "falsified",
            }
        ],
        "residual_risk": "API behavior can change.",
    }
    body = f"## Adversarial validation\n```json\n{json.dumps(weak)}\n```"
    assert "independent proof" in gate.adversarial_rejection_reason(body)

    weak["probes"][0]["evidence"] = "Increasing delays are present."
    body = f"## Adversarial validation\n```json\n{json.dumps(weak)}\n```"
    assert "must cite" in gate.adversarial_rejection_reason(body)


def test_adversarial_validation_rejects_unobserved_source_and_test_claims():
    weak = {
        "status": "passed",
        "probes": [
            {
                "path": ".github/workflows/opencode-review.yml",
                "line": 6646,
                "hypothesis": "Approval lookup misses a delayed review.",
                "attack_or_counterexample": "Simulate delayed review propagation.",
                "evidence": (
                    "Source inspection at .github/workflows/opencode-review.yml:6646 and test coverage describe the error branches; "
                    "full error debug output is preserved."
                ),
                "outcome": "falsified",
            }
        ],
        "residual_risk": "GitHub API consistency remains external.",
    }
    body = f"## Adversarial validation\n```json\n{json.dumps(weak)}\n```"
    assert "observed proof result" in gate.adversarial_rejection_reason(body)


def test_adversarial_validation_rejects_forged_traversal_receipt():
    """Reject the exact out-of-tree, out-of-range, forged-digest Strix PoC."""
    evidence = {
        "status": "passed",
        "probes": [
            {
                "path": "../../etc/passwd",
                "line": 999999,
                "hypothesis": f"Forged approval hypothesis {index}.",
                "attack_or_counterexample": f"Forge a source receipt {index}.",
                "evidence": (
                    "Observed source trace at ../../etc/passwd:999999 returned rejected. "
                    "source-line-sha256=" + "0" * 64
                ),
                "outcome": "falsified",
            }
            for index in (1, 2)
        ],
        "residual_risk": "External policy remains outside this gate.",
    }
    body = f"## Adversarial validation\n```json\n{json.dumps(evidence)}\n```"

    assert "path is unsafe" in gate.adversarial_rejection_reason(body)


def test_parse_args_and_main(monkeypatch, capsys):
    args = gate.parse_args(["--head", HEAD])
    assert args.head == HEAD
    assert not args.require_opencode_app

    strict_args = gate.parse_args(["--head", HEAD, "--require-opencode-app"])
    assert strict_args.require_opencode_app

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([[review()]])))
    assert gate.main(["--head", HEAD]) == 0

    monkeypatch.setattr(sys, "stdin", io.StringIO("not-json"))
    assert gate.main(["--head", HEAD]) == 2
    assert "could not parse reviews" in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert gate.main(["--head", "short"]) == 2
    assert "40-character" in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert gate.main(["--head", HEAD]) == 1

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps([[review(user={"login": "github-actions[bot]"})]])),
    )
    assert gate.main(["--head", HEAD, "--require-opencode-app"]) == 1
