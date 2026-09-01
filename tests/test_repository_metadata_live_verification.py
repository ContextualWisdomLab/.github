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


class FakeResponse:
    """Minimal context-managed HTTPS response used by Pages reachability tests."""

    def __init__(self, payload=b"x"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=-1):
        return self.payload[:size]


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
            "status": "built",
            "html_url": "https://contextualwisdomlab.github.io/Repo/",
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
    monkeypatch.setattr(RECONCILER, "urlopen", lambda *args, **kwargs: FakeResponse())


def test_pages_publication_ready_requires_build_https_and_content(monkeypatch) -> None:
    """A Pages configuration is complete only when its built site is reachable."""

    ready = {
        "status": "built",
        "html_url": "https://contextualwisdomlab.github.io/Repo/",
    }
    seen = []

    def open_ok(request, timeout):
        seen.append((request.full_url, request.headers["User-agent"], timeout))
        return FakeResponse(b"published")

    monkeypatch.setattr(RECONCILER, "urlopen", open_ok)
    RECONCILER._pages_publication_ready("Repo", ready)
    assert seen == [
        (
            "https://contextualwisdomlab.github.io/Repo/",
            "ContextualWisdomLab-repository-metadata-reconcile",
            10,
        )
    ]

    with pytest.raises(RuntimeError, match="not built"):
        RECONCILER._pages_publication_ready("Repo", {**ready, "status": "building"})
    with pytest.raises(RuntimeError, match="URL is invalid"):
        RECONCILER._pages_publication_ready("Repo", {**ready, "html_url": "http://x"})

    monkeypatch.setattr(
        RECONCILER, "urlopen", lambda *args, **kwargs: FakeResponse(b"")
    )
    with pytest.raises(RuntimeError, match="empty content"):
        RECONCILER._pages_publication_ready("Repo", ready)

    def open_error(*args, **kwargs):
        raise RECONCILER.URLError("offline")

    monkeypatch.setattr(RECONCILER, "urlopen", open_error)
    with pytest.raises(RuntimeError, match="not reachable"):
        RECONCILER._pages_publication_ready("Repo", ready)


def test_verify_repository_accepts_converged_disabled_and_enabled_pages(
    monkeypatch,
) -> None:
    """Verification succeeds only on freshly re-read converged public state."""

    install_live_state(monkeypatch)
    RECONCILER.verify_repository("Repo", desired())

    install_live_state(monkeypatch, badge=True, docs=True, pages=True)
    RECONCILER.verify_repository("Repo", desired(deepwiki=True, pages=True))


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
                    "status": "built",
                    "html_url": "https://contextualwisdomlab.github.io/Repo/",
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


def test_verify_repository_rejects_unready_published_pages(monkeypatch) -> None:
    """A correctly configured but still-building Pages site is not completion."""

    install_live_state(
        monkeypatch,
        badge=True,
        docs=True,
        pages=True,
        page_config={
            "build_type": "legacy",
            "status": "building",
            "html_url": "https://contextualwisdomlab.github.io/Repo/",
            "source": {"branch": "main", "path": "/docs"},
        },
    )
    with pytest.raises(RuntimeError, match="not built"):
        RECONCILER.verify_repository("Repo", desired(deepwiki=True, pages=True))


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
