"""Executable regressions for observed Noema review false-negative shapes.

These cases are grounded in externally demonstrated review findings rather than
claims of benchmark superiority.  They keep the trusted review admission layer
honest about exact source coordinates and require the model prompt/validator to
attack more than one high-value defect class on material changes.
"""

from __future__ import annotations

import json

import pytest

from scripts.ci import noema_review_gate as noema


DIFF = """diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+new = 1
"""


def _source_ref() -> dict[str, object]:
    return {"path": "src/tool.py", "line": 1, "side": "RIGHT"}


def _class_evidence(kind: str) -> dict[str, dict[str, object]]:
    return {
        field: {
            **_source_ref(),
            "source_excerpt": "new = 1",
            "claim_role": noema.OBSERVED_REVIEW_PROBE_CLAIM_ROLES[kind][field],
            "observation": (
                f"new = 1 is exact source evidence for structured role {index}: {field}."
            ),
        }
        for index, field in enumerate(
            noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind],
            start=1,
        )
    }


def _probe(kind: str, *, hypothesis: str) -> dict[str, object]:
    return {
        **_source_ref(),
        "probe_kind": kind,
        "class_evidence": _class_evidence(kind),
        "hypothesis": hypothesis,
        "attack_or_counterexample": f"Attack {kind} at the exact changed line.",
        "evidence": f"Observed source-bound evidence for {kind}.",
        "outcome": "falsified",
    }


def _verdict() -> dict[str, object]:
    return {
        "decision": "approve",
        "summary": "Two independently classified defect shapes were attacked.",
        "findings": [],
        "reviewed_lines": [{**_source_ref(), "analysis": "Reviewed the exact changed line."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No runtime integration exercise was available in this unit fixture.",
            "probes": [
                _probe("mutable_alias", hypothesis="Caller-owned mutable state may escape validation."),
                _probe(
                    "time_of_check_time_of_use",
                    hypothesis="A changing getter may differ between validation and use.",
                ),
            ],
        },
    }


@pytest.mark.parametrize("container", [True, False])
def test_boolean_reviewed_line_cannot_alias_integer_coordinate(container: bool) -> None:
    verdict = _verdict()
    verdict["reviewed_lines"][0]["line"] = container

    with pytest.raises(noema.NoemaModelOutputError, match="canonical positive integer line"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


@pytest.mark.parametrize("container", [True, False])
def test_boolean_probe_line_cannot_alias_integer_coordinate(container: bool) -> None:
    verdict = _verdict()
    verdict["adversarial_validation"]["probes"][0]["line"] = container

    with pytest.raises(noema.NoemaModelOutputError, match="canonical positive integer line"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_material_review_requires_distinct_observed_defect_classes() -> None:
    verdict = _verdict()
    verdict["adversarial_validation"]["probes"] = [
        _probe("mutable_alias", hypothesis="First mutable-alias wording."),
        _probe("mutable_alias", hypothesis="Different prose, same defect shape."),
    ]

    with pytest.raises(noema.NoemaModelOutputError, match="distinct probe_kind"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


@pytest.mark.parametrize("probe_kind", [[], {}, "unknown_shape"])
def test_probe_kind_fails_closed_on_malformed_or_unknown_values(probe_kind: object) -> None:
    verdict = _verdict()
    verdict["adversarial_validation"]["probes"][0]["probe_kind"] = probe_kind

    with pytest.raises(noema.NoemaModelOutputError, match="observed defect taxonomy"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_class_evidence_must_be_source_bound_to_the_probe_location() -> None:
    verdict = _verdict()
    probe = verdict["adversarial_validation"]["probes"][0]
    probe["class_evidence"]["mutation_attempt"] = {
        "path": "src/tool.py",
        "line": 1,
        "side": "LEFT",
        "source_excerpt": "old = 1",
        "claim_role": noema.OBSERVED_REVIEW_PROBE_CLAIM_ROLES["mutable_alias"]["mutation_attempt"],
        "observation": "old = 1 is exact source evidence for the mutation-attempt role.",
    }

    with pytest.raises(noema.NoemaModelOutputError, match="must bind to the probe location"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_valid_observed_defect_taxonomy_verdict_is_accepted() -> None:
    noema.validate_substantive_verdict(_verdict(), DIFF, ["src/tool.py"])


def test_noema_prompt_names_every_observed_defect_class(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(noema, "reject_private_llm_url", lambda _url: None)
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)
    monkeypatch.setattr(
        noema,
        "fetch_pr",
        lambda _repo, _number: {"state": "OPEN", "headRefOid": "a" * 40},
    )
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            payload = {"choices": [{"message": {"content": json.dumps({"decision": "comment", "summary": "ok", "findings": []})}}]}
            return json.dumps(payload).encode("utf-8")

    class Opener:
        def open(self, request, timeout=None):
            seen["request"] = json.loads(request.data.decode("utf-8"))
            return Response()

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())
    pr = {"title": "fixture", "headRefOid": "a" * 40}

    noema.call_llm(
        "owner/repo",
        7,
        pr,
        DIFF,
        False,
        "a" * 40,
        changed_paths=["src/tool.py"],
    )

    prompt = seen["request"]["messages"][1]["content"]
    for probe_kind in noema.OBSERVED_REVIEW_PROBE_KINDS:
        assert probe_kind in prompt
    assert "class_evidence" in prompt
    assert "exact changed-side" in prompt
    assert "source_excerpt" in prompt
    assert "workflow-starting credential" in prompt
    assert "downstream required checks" in prompt
