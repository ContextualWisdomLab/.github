"""Reject author-owned credentials in the legacy direct Noema entry point."""
from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as gate

HEAD = "a" * 40


def _bind(monkeypatch, author):
    """Replace network/model boundaries with labelled synthetic witnesses."""
    pr = {"state": "OPEN", "headRefOid": HEAD, "baseRefOid": "b" * 40,
          "isDraft": False, "author": {"login": author} if author else None}
    monkeypatch.setattr(gate, "fetch_pr", lambda *_: pr)
    monkeypatch.setattr(gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(gate, "existing_noema_review", lambda *_: False)
    monkeypatch.setattr(gate, "fetch_diff", lambda *_: ("diff", False))
    monkeypatch.setattr(gate, "fetch_changed_files", lambda *_: [("src/a.py", "MODIFIED")])
    monkeypatch.setattr(gate, "build_review_context", lambda *_: "context")
    return pr


@pytest.mark.parametrize("author", (None, "cwl-noema-review[bot]", "CWL-Noema-Review[bot]"))
def test_direct_entry_rejects_unknown_or_self_author(monkeypatch, author):
    """Neither unknown author nor case variation may permit self-review."""
    _bind(monkeypatch, author)
    monkeypatch.setattr(gate, "call_llm", lambda *_: pytest.fail("model reached before author admission"))
    with pytest.raises(RuntimeError, match="author"):
        gate.inspect_and_review("ContextualWisdomLab/example", 7, HEAD)


def test_direct_entry_rechecks_author_before_publication(monkeypatch):
    """The live author must be revalidated after model work."""
    pr = _bind(monkeypatch, "seonghobae")
    def model(*_):
        pr["author"] = {"login": "cwl-noema-review[bot]"}
        return {"decision": "approve"}
    monkeypatch.setattr(gate, "call_llm", model)
    monkeypatch.setattr(
        gate,
        "submit_review",
        lambda *_: pytest.fail("author-owned review was published"),
    )
    with pytest.raises(RuntimeError, match="author"):
        gate.inspect_and_review("ContextualWisdomLab/example", 7, HEAD)


def test_direct_entry_permits_independent_actor(monkeypatch):
    """A distinct App can publish its own substantive verdict."""
    _bind(monkeypatch, "seonghobae")
    monkeypatch.setattr(gate, "call_llm", lambda *_: {"decision": "approve"})
    submitted = []
    monkeypatch.setattr(gate, "submit_review", lambda *args: submitted.append(args))
    assert gate.inspect_and_review("ContextualWisdomLab/example", 7, HEAD) == 0
    assert len(submitted) == 1
    assert submitted[0][3] == "cwl-noema-review[bot]"
