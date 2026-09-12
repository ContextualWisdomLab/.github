"""Live post-apply verification contracts for repository public metadata."""

from __future__ import annotations

import argparse
import importlib.util
import json
from io import BytesIO
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


class FakeOpener:
    """Minimal redirect-controlled opener used by Pages reachability tests."""

    def __init__(self, *, response=None, error=None, seen=None):
        self.response = response or FakeResponse()
        self.error = error
        self.seen = seen

    def open(self, request, timeout):
        if self.seen is not None:
            self.seen.append((request.full_url, request.headers["User-agent"], timeout))
        if self.error is not None:
            raise self.error
        return self.response


def test_pages_transport_error_closes_response_body(monkeypatch) -> None:
    body = BytesIO(b"redirect")
    error = RECONCILER.HTTPError(
        "https://contextualwisdomlab.github.io/Repo/", 302, "redirect", {}, body
    )
    monkeypatch.setattr(
        RECONCILER, "build_opener", lambda *_args: FakeOpener(error=error)
    )

    with pytest.raises(RuntimeError, match="not reachable"):
        RECONCILER._pages_publication_ready(
            "Repo",
            {
                "status": "built",
                "html_url": "https://contextualwisdomlab.github.io/Repo/",
            },
        )

    assert body.closed


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
    monkeypatch.setattr(
        RECONCILER, "build_opener", lambda *args: FakeOpener()
    )


def test_pages_publication_ready_confines_origin_redirects_and_content(
    monkeypatch,
) -> None:
    """Published Pages checks stay on the owned origin and require non-empty content."""

    ready = {
        "status": "built",
        "html_url": "https://contextualwisdomlab.github.io/Repo/",
    }
    seen = []
    handlers = []

    def build_ok(handler):
        handlers.append(handler)
        return FakeOpener(response=FakeResponse(b"published"), seen=seen)

    monkeypatch.setattr(RECONCILER, "build_opener", build_ok)
    assert RECONCILER._pages_url_is_expected(RECONCILER.PAGES_BASE_URL)
    assert RECONCILER._pages_url_is_expected(ready["html_url"])
    assert not RECONCILER._pages_url_is_expected(None)
    assert not RECONCILER._pages_url_is_expected("https://example.com/")
    assert not RECONCILER._pages_url_is_expected(
        "https://contextualwisdomlab.github.io.evil.example/"
    )
    assert not RECONCILER._pages_url_is_expected(
        "https://contextualwisdomlab.github.io@127.0.0.1/"
    )

    RECONCILER._pages_publication_ready("Repo", ready)
    assert seen == [
        (
            "https://contextualwisdomlab.github.io/Repo/",
            "ContextualWisdomLab-repository-metadata-reconcile",
            10,
        )
    ]
    assert len(handlers) == 1
    assert isinstance(handlers[0], RECONCILER._NoPagesRedirects)
    from urllib.error import HTTPError
    with pytest.raises(HTTPError) as response_error:
        handlers[0].redirect_request(
            RECONCILER.Request("https://example.com"), None, 302, "redirect", {}, "http://127.0.0.1/"
        )
    response_error.value.close()

    with pytest.raises(RuntimeError, match="not built"):
        RECONCILER._pages_publication_ready("Repo", {**ready, "status": "building"})
    for unsafe_url in [
        "http://contextualwisdomlab.github.io/Repo/",
        "https://example.com/",
        "https://contextualwisdomlab.github.io.evil.example/",
    ]:
        with pytest.raises(RuntimeError, match="URL is invalid"):
            RECONCILER._pages_publication_ready(
                "Repo", {**ready, "html_url": unsafe_url}
            )

    monkeypatch.setattr(
        RECONCILER,
        "build_opener",
        lambda *args: FakeOpener(response=FakeResponse(b"")),
    )
    with pytest.raises(RuntimeError, match="empty content"):
        RECONCILER._pages_publication_ready("Repo", ready)

    monkeypatch.setattr(
        RECONCILER,
        "build_opener",
        lambda *args: FakeOpener(error=RECONCILER.URLError("offline")),
    )
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
