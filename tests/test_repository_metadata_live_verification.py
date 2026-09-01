"""Live post-apply verification contracts for repository public metadata."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_metadata.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_metadata", SCRIPT)
assert SPEC and SPEC.loader
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def desired(**overrides):
    """Return one minimal desired public state."""

    state = {
        "description": "Useful product.",
        "topics": ["python"],
        "deepwiki": False,
        "pages": False,
    }
    state.update(overrides)
    return state


def install_live_state(
    monkeypatch,
    *,
    description="Useful product.",
    default_branch="main",
    topics=None,
    badge=False,
    docs=False,
    pages=False,
    page_config=None,
):
    """Install deterministic live-state probes for verification tests."""

    if topics is None:
        topics = ["python"]
    if page_config is None:
        page_config = {
            "build_type": "legacy",
            "source": {"branch": default_branch, "path": "/docs"},
        }

    def gh_api(method, endpoint, **kwargs):
        assert method == "GET"
        if endpoint.endswith("/topics"):
            return json.dumps({"names": topics})
        return json.dumps(
            {"default_branch": default_branch, "description": description}
        )

    monkeypatch.setattr(RECONCILER, "_gh_api", gh_api)
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: badge)
    monkeypatch.setattr(RECONCILER, "_docs_index_exists", lambda *args: docs)
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: pages)
    monkeypatch.setattr(
        RECONCILER, "_pages_configuration", lambda *args: page_config
    )


def test_verify_repository_accepts_converged_disabled_and_enabled_pages(
    monkeypatch,
) -> None:
    """Verification succeeds only on freshly re-read converged public state."""

    install_live_state(monkeypatch)
    RECONCILER.verify_repository("Repo", desired())

    install_live_state(monkeypatch, badge=True, docs=True, pages=True)
    RECONCILER.verify_repository(
        "Repo", desired(deepwiki=True, pages=True)
    )


@pytest.mark.parametrize(
    ("state", "wanted", "message"),
    [
        ({"default_branch": ""}, {}, "default branch"),
        ({"description": "wrong"}, {}, "description did not converge"),
        ({"topics": ["wrong"]}, {}, "topics did not converge"),
        ({"badge": True}, {}, "DeepWiki state did not converge"),
        (
            {"badge": True, "docs": False},
            {"deepwiki": True, "pages": True},
            "Pages source did not converge",
        ),
        (
            {"badge": True, "docs": True, "pages": False},
            {"deepwiki": True, "pages": True},
            "was not published",
        ),
        (
            {
                "badge": True,
                "docs": True,
                "pages": True,
                "page_config": {
                    "build_type": "workflow",
                    "source": {"branch": "main", "path": "/docs"},
                },
            },
            {"deepwiki": True, "pages": True},
            "configuration did not converge",
        ),
        ({"pages": True}, {}, "remained published"),
    ],
)
def test_verify_repository_rejects_every_public_surface_drift(
    monkeypatch, state, wanted, message
) -> None:
    """Each independently observable public-surface mismatch fails verification."""

    install_live_state(monkeypatch, **state)
    with pytest.raises(RuntimeError, match=message):
        RECONCILER.verify_repository("Repo", desired(**wanted))


def test_main_verify_only_uses_read_only_verifier(monkeypatch, tmp_path: Path) -> None:
    """Verify-only mode never calls the mutation path."""

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {"Repo": desired()},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(
            manifest=manifest,
            validate_only=False,
            verify_only=True,
            repository=[],
        ),
    )
    seen = []
    monkeypatch.setattr(
        RECONCILER,
        "verify_repository",
        lambda repository, state: seen.append(repository),
    )
    monkeypatch.setattr(
        RECONCILER,
        "reconcile_repository",
        lambda *args: pytest.fail("mutation path used in verify-only mode"),
    )

    assert RECONCILER.main() == 0
    assert seen == ["Repo"]
