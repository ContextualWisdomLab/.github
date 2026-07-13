import io
import json
import sys

import pytest

from scripts.ci import opencode_existing_approval_gate as gate


HEAD = "a" * 40


def valid_body(head: str = HEAD) -> str:
    """Build a real-model review body with structured adversarial evidence."""
    evidence = {
        "status": "passed",
        "probes": [
            {
                "path": ".github/workflows/opencode-review.yml",
                "line": 1,
                "hypothesis": "A fallback approval could be reused.",
                "attack_or_counterexample": "Supply a deterministic approval body.",
                "evidence": "The gate rejected the fallback marker.",
                "outcome": "falsified",
            }
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
            lambda value: value.update(body=value["body"] + "\ndeterministic fallback approval"),
            "fallback",
        ),
        (
            lambda value: value.update(body=value["body"].replace(gate.PRIMARY_APPROVAL_MARKER, "missing")),
            "real-model approval marker",
        ),
        (lambda value: value.update(body=value["body"].replace("- Result: APPROVE", "")), "APPROVE result"),
        (lambda value: value.update(body=value["body"].replace(f"- Head SHA: `{HEAD}`", "")), "current-head"),
        (lambda value: value.update(body=value["body"].replace("- Workflow run: 123", "")), "workflow run"),
        (lambda value: value.update(body=value["body"].replace("- Workflow attempt: 2", "")), "workflow attempt"),
        (
            lambda value: value.update(body=value["body"].replace("```json", "```text")),
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
        ({"status": "passed", "probes": [], "residual_risk": "risk"}, "probes are empty"),
        ({"status": "passed", "probes": ["bad"], "residual_risk": "risk"}, "not an object"),
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


def test_parse_args_and_main(monkeypatch, capsys):
    assert gate.parse_args(["--head", HEAD]).head == HEAD

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
