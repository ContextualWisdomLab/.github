"""Executable regressions for the Noema two-phase reviewer handoff."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".github" / "actions" / "noema-review" / "two_phase.py"
HEAD = "a" * 40
BASE = "b" * 40


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("noema_two_phase_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_live_gate(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": False,
            "headRefOid": HEAD,
            "baseRefOid": BASE,
        },
    )
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    monkeypatch.setattr(module.gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: False)


def test_prepare_seals_validated_verdict_without_publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preparation performs model work but cannot submit GitHub review evidence."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    monkeypatch.setattr(module.gate, "fetch_diff", lambda _repo, _number: ("diff", False))
    monkeypatch.setattr(module.gate, "fetch_changed_files", lambda _repo, _number: [("src/a.py", "MODIFIED")])
    monkeypatch.setattr(module.gate, "build_review_context", lambda *_args: "context")
    verdict = {"decision": "approve", "summary": "bounded"}
    monkeypatch.setattr(module.gate, "call_llm", lambda *_args: verdict)
    monkeypatch.setattr(module.gate, "submit_review", lambda *_args: pytest.fail("preparation must never publish"))
    envelope = tmp_path / "verdict.json"

    assert module.prepare_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    payload = module._read_envelope(envelope)
    assert payload["verdict"] == verdict
    assert payload["expected_base"] == BASE


def test_publish_refetches_exact_head_and_base_with_fresh_actor_and_removes_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publication rebinds repository/head/base/actor and consumes the private handoff."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    envelope = tmp_path / "verdict.json"
    verdict = {"decision": "approve", "summary": "bounded"}
    module._write_envelope(envelope, {
        "schema_version": module.ENVELOPE_SCHEMA_VERSION,
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 7,
        "expected_head": HEAD,
        "expected_base": BASE,
        "verdict": verdict,
    })
    submitted: list[tuple[object, ...]] = []
    monkeypatch.setattr(module.gate, "submit_review", lambda *args: submitted.append(args))

    assert module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert len(submitted) == 1
    assert submitted[0][0:2] == ("ContextualWisdomLab/example", 7)
    assert submitted[0][3] == "cwl-noema-review[bot]"
    assert submitted[0][4] == verdict
    assert not envelope.exists()


def test_publish_rejects_stale_head_and_never_submits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A moved head invalidates predecessor model evidence before publication."""
    module = _load_module()
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": False,
            "headRefOid": "c" * 40,
            "baseRefOid": BASE,
        },
    )

    def stale(_pr: object, _head: str) -> None:
        raise RuntimeError("stale")

    monkeypatch.setattr(module.gate, "require_expected_head", stale)
    monkeypatch.setattr(module.gate, "submit_review", lambda *_args: pytest.fail("stale evidence must not publish"))
    envelope = tmp_path / "verdict.json"
    module._write_envelope(envelope, {
        "schema_version": module.ENVELOPE_SCHEMA_VERSION,
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 7,
        "expected_head": HEAD,
        "expected_base": BASE,
        "verdict": {"decision": "approve"},
    })

    assert module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert not envelope.exists()


def test_publish_rejects_base_drift_with_unchanged_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A moved base invalidates the prepared diff/context even when the head is unchanged."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": False,
            "headRefOid": HEAD,
            "baseRefOid": "c" * 40,
        },
    )
    envelope = tmp_path / "verdict.json"
    module._write_envelope(envelope, {
        "schema_version": module.ENVELOPE_SCHEMA_VERSION,
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 7,
        "expected_head": HEAD,
        "expected_base": BASE,
        "verdict": {"decision": "approve", "summary": "stale base"},
    })
    monkeypatch.setattr(module.gate, "submit_review", lambda *_args: pytest.fail("base-drifted evidence must not publish"))

    assert module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert not envelope.exists()


def test_prepare_skip_creates_no_publishable_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Draft skip semantics stay non-failing and cannot fabricate evidence."""
    module = _load_module()
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": True,
            "headRefOid": HEAD,
            "baseRefOid": BASE,
        },
    )
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    monkeypatch.setattr(module.gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: False)
    monkeypatch.setattr(module.gate, "call_llm", lambda *_args: pytest.fail("draft must not call the model"))
    envelope = tmp_path / "verdict.json"

    assert module.prepare_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert not envelope.exists()


@pytest.mark.parametrize("skip_kind", ["closed_or_stale", "draft", "existing_review"])
def test_model_admission_skips_ineligible_review_before_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skip_kind: str,
) -> None:
    """The shared prepare predicate must decline model work without fabricating admission."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    if skip_kind == "closed_or_stale":
        monkeypatch.setattr(
            module.gate,
            "require_expected_head",
            lambda _pr, _head: (_ for _ in ()).throw(RuntimeError("closed or stale")),
        )
    elif skip_kind == "draft":
        monkeypatch.setattr(
            module.gate,
            "fetch_pr",
            lambda _repo, _number: {
                "isDraft": True,
                "headRefOid": HEAD,
                "baseRefOid": BASE,
            },
        )
    else:
        monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: True)
    marker = tmp_path / "model-admission.json"

    assert module.admit_model_work("ContextualWisdomLab/example", 7, HEAD, marker) == 0
    assert not marker.exists()


def test_model_admission_reuses_prepare_identity_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eligible model work is admitted only after the current prepare identity checks."""
    module = _load_module()
    _patch_live_gate(monkeypatch, module)
    marker = tmp_path / "model-admission.json"

    assert module.admit_model_work("ContextualWisdomLab/example", 7, HEAD, marker) == 0
    assert module._read_envelope(marker) == {
        "expected_base": BASE,
        "expected_head": HEAD,
        "pull_request_number": 7,
        "repository": "ContextualWisdomLab/example",
        "schema_version": module.ENVELOPE_SCHEMA_VERSION,
    }


@pytest.mark.parametrize("invalid_identity", ["head", "base", "actor"])
def test_model_admission_fails_closed_before_skipping_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_identity: str,
) -> None:
    """Draft status cannot bypass the prepare path's head, base, or actor checks."""
    module = _load_module()
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": True,
            "headRefOid": HEAD,
            "baseRefOid": "short" if invalid_identity == "base" else BASE,
        },
    )
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(
        module.gate,
        "current_actor",
        lambda: "" if invalid_identity == "actor" else "cwl-noema-review[bot]",
    )
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    marker = tmp_path / "model-admission.json"

    expected_head = "short" if invalid_identity == "head" else HEAD
    with pytest.raises(RuntimeError):
        module.admit_model_work("ContextualWisdomLab/example", 7, expected_head, marker)
    assert not marker.exists()


def test_prepare_rechecks_eligibility_after_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PR becoming Draft after admission still blocks the model call."""
    module = _load_module()
    states = iter((False, True))
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": next(states),
            "headRefOid": HEAD,
            "baseRefOid": BASE,
        },
    )
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    monkeypatch.setattr(module.gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: False)
    monkeypatch.setattr(module.gate, "call_llm", lambda *_args: pytest.fail("Draft must not call the model"))
    marker = tmp_path / "model-admission.json"
    envelope = tmp_path / "verdict.json"

    assert module.admit_model_work("ContextualWisdomLab/example", 7, HEAD, marker) == 0
    assert marker.exists()
    assert module.prepare_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert not envelope.exists()


def test_publish_cleans_untrusted_envelope_even_when_read_validation_fails(tmp_path: Path) -> None:
    """Malformed handoff state cannot linger after a failed publication attempt."""
    module = _load_module()
    envelope = tmp_path / "verdict.json"
    envelope.write_text("{}\n", encoding="utf-8")
    os.chmod(envelope, 0o644)

    with pytest.raises(RuntimeError, match="permissions"):
        module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope)
    assert not envelope.exists()


def test_reader_rejects_hardlinked_aliases(tmp_path: Path) -> None:
    """A caller-owned alias cannot mutate the supposedly private handoff file."""
    module = _load_module()
    envelope = tmp_path / "verdict.json"
    alias = tmp_path / "alias.json"
    module._write_envelope(envelope, {"schema_version": module.ENVELOPE_SCHEMA_VERSION})
    os.link(envelope, alias)
    try:
        with pytest.raises(RuntimeError, match="single-link"):
            module._read_envelope(envelope)
    finally:
        envelope.unlink(missing_ok=True)
        alias.unlink(missing_ok=True)
