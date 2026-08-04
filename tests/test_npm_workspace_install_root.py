"""Tests for trusted npm workspace install-root resolution."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

import pytest

from scripts.ci import npm_workspace_install_root as module
from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root
from tests.npm_workspace_test_support import (
    commit_all as _commit,
    run_git as _git,
    write_json as _write_json,
)


def _init_repo(repo: Path) -> None:
    """Initialize a deterministic local Git repository for one test."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "Coverage Tests")


def _workspace(
    repo: Path,
    workspaces: object = None,
    *,
    intermediate: bool = False,
) -> tuple[Path, str]:
    """Create and commit a root npm workspace with one desktop package."""
    _init_repo(repo)
    root_manifest: dict[str, object] = {"name": "root", "private": True}
    root_manifest["workspaces"] = workspaces if workspaces is not None else ["apps/*"]
    _write_json(repo / "package.json", root_manifest)
    desktop = repo / "apps" / "desktop"
    _write_json(desktop / "package.json", {"name": "desktop"})
    _write_json(
        repo / "package-lock.json",
        {
            "name": "root",
            "lockfileVersion": 3,
            "packages": {"": {"name": "root"}, "apps/desktop": {"name": "desktop"}},
        },
    )
    if intermediate:
        _write_json(repo / "apps" / "package.json", {"name": "apps"})
        _write_json(
            repo / "apps" / "package-lock.json",
            {"name": "apps", "lockfileVersion": 3, "packages": {"": {}}},
        )
    return desktop, _commit(repo)


def _resolve(repo: Path, package: Path, base: str, head: str | None = None) -> str:
    """Call the production resolver with an optional distinct head SHA."""
    return resolve_install_root(repo, package, base, head or base)


def test_resolves_repository_root_for_nested_workspace(tmp_path: Path) -> None:
    """A nested workspace uses the ancestor repository-root npm lock."""
    desktop, revision = _workspace(tmp_path)
    assert _resolve(tmp_path, desktop, revision) == "."


def test_supports_object_valued_workspace_packages(tmp_path: Path) -> None:
    """npm's object form with a packages array is recognized."""
    desktop, revision = _workspace(tmp_path, {"packages": ["apps/*"]})
    assert _resolve(tmp_path, desktop, revision) == "."


def test_prefers_the_nearest_package_local_lock(tmp_path: Path) -> None:
    """A package-local lock takes precedence over an ancestor workspace lock."""
    desktop, base = _workspace(tmp_path)
    _write_json(
        desktop / "package-lock.json",
        {"name": "desktop", "lockfileVersion": 3, "packages": {"": {}}},
    )
    head = _commit(tmp_path, "local lock")
    assert _resolve(tmp_path, desktop, base, head) == "apps/desktop"


def test_skips_non_owner_intermediate_lock_and_checks_full_ancestry(
    tmp_path: Path,
) -> None:
    """An unrelated intermediate npm project does not hide the root workspace."""
    desktop, revision = _workspace(tmp_path, intermediate=True)
    assert _resolve(tmp_path, desktop, revision) == "."


def test_rejects_package_not_declared_by_any_workspace(tmp_path: Path) -> None:
    """An unrelated nested package cannot consume an ancestor lock cache."""
    desktop, revision = _workspace(tmp_path, ["packages/*"])
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        _resolve(tmp_path, desktop, revision)


def test_rejects_package_missing_from_lock_map(tmp_path: Path) -> None:
    """Workspace declaration alone is insufficient without an exact lock entry."""
    desktop, _base = _workspace(tmp_path)
    lock = json.loads((tmp_path / "package-lock.json").read_text(encoding="utf-8"))
    del lock["packages"]["apps/desktop"]
    _write_json(tmp_path / "package-lock.json", lock)
    revision = _commit(tmp_path, "missing package entry")
    with pytest.raises(ResolutionError, match="no validated package-lock"):
        _resolve(tmp_path, desktop, revision)


@pytest.mark.parametrize(
    "pattern",
    [
        "",
        42,
        "!apps/*",
        "apps\\*",
        "/apps/*",
        "../apps/*",
        "node_modules/*",
        "apps/\x00*",
        "apps/**desktop",
        "apps/***",
        "apps/{desktop,web}",
        "apps/(desktop|web)",
        "apps/[desktop",
        "apps/desktop]",
    ],
)
def test_rejects_unsafe_workspace_patterns(tmp_path: Path, pattern: object) -> None:
    """Workspace patterns are constrained to safe relative path globs."""
    desktop, revision = _workspace(tmp_path, [pattern])
    with pytest.raises(ResolutionError, match="workspace pattern"):
        _resolve(tmp_path, desktop, revision)


@pytest.mark.parametrize(
    ("content", "match"),
    [("not-json", "invalid JSON"), ("[]", "must be a JSON object")],
)
def test_rejects_invalid_workspace_manifest(
    tmp_path: Path, content: str, match: str
) -> None:
    """Workspace ownership cannot be derived from malformed head JSON."""
    desktop, base = _workspace(tmp_path)
    (tmp_path / "package.json").write_text(content, encoding="utf-8")
    head = _commit(tmp_path, "bad manifest")
    with pytest.raises(ResolutionError, match=match):
        _resolve(tmp_path, desktop, base, head)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not-json", "invalid JSON"),
        ("[]", "must be a JSON object"),
        (json.dumps({"packages": {"apps/desktop": {}}}), "lockfileVersion"),
        (json.dumps({"lockfileVersion": True, "packages": {}}), "lockfileVersion"),
        (json.dumps({"lockfileVersion": 3, "packages": []}), "packages object"),
    ],
)
def test_rejects_invalid_lock_metadata(
    tmp_path: Path, payload: str, match: str
) -> None:
    """Malformed lock metadata cannot establish npm ownership."""
    desktop, base = _workspace(tmp_path)
    (tmp_path / "package-lock.json").write_text(payload, encoding="utf-8")
    head = _commit(tmp_path, "bad lock")
    with pytest.raises(ResolutionError, match=match):
        _resolve(tmp_path, desktop, base, head)


def test_rejects_package_directory_escape(tmp_path: Path) -> None:
    """The requested package must remain beneath the validated repository root."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_json(repo / "package.json", {"name": "repo"})
    revision = _commit(repo)
    outside = tmp_path / "outside"
    _write_json(outside / "package.json", {"name": "outside"})
    with pytest.raises(ResolutionError, match="escaped"):
        _resolve(repo, outside, revision)


def test_rejects_symlinked_package_directory(tmp_path: Path) -> None:
    """A symlink cannot redirect package reads inside or outside the tree."""
    repo = tmp_path / "repo"
    desktop, revision = _workspace(repo)
    link = repo / "linked"
    try:
        link.symlink_to(desktop, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(ResolutionError, match="symlink"):
        _resolve(repo, link, revision)


def test_rejects_repository_root_symlink(tmp_path: Path) -> None:
    """The trusted repository root cannot be redirected through a symlink."""
    real_root = tmp_path / "real"
    _workspace(real_root)
    link = tmp_path / "link"
    try:
        link.symlink_t²È="24€€…ÍÍ•ÉÐ}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°‰…Í”°¡•…¤€ôô€ˆ¸ˆ(()‘•˜Ñ•ÍÑ}…•ÁÑÍ}‰½Õ¹‘•‘}±½­}¡…¹•}‰•ÑÝ••¹}‰…Í•}…¹‘}¡•…¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰¡…¹•¡•…±½¬É•µ…¥¹Ì•±¥¥‰±”™½È•á…Ðµ…¹¥™•ÍÐµÉ••¥ÁÐ¡•­Ì¸ˆˆˆ(€€€‘•Í­Ñ½À°‰…Í”€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ ¤(€€€±½¬€ô©Í½¸¹±½…‘Ì ¡ÑµÁ}Á…Ñ €¼€‰Á…­…”µ±½¬¹©Í½¸ˆ¤¹É•…‘}Ñ•áÐ¡•¹½‘¥¹œô‰ÕÑ˜´àˆ¤¤(€€€±½­l‰Á…­…•Ì‰ul‰…ÁÁÌ½‘•Í­Ñ½À‰ul‰Ù•ÉÍ¥½¸‰t€ô€ˆÄ¸À¸Àˆ(€€€}ÝÉ¥Ñ•}©Í½¸¡ÑµÁ}Á…Ñ €¼€‰Á…­…”µ±½¬¹©Í½¸ˆ°±½¬¤(€€€¡•…€ô}½µµ¥Ð¡ÑµÁ}Á…Ñ °€‰¡…¹”±½¬ˆ¤(€€€…ÍÍ•ÉÐ}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°‰…Í”°¡•…¤€ôô€ˆ¸ˆ(()‘•˜Ñ•ÍÑ}…•ÁÑÍ}Ý½É­ÍÁ…•}µ…¹¥™•ÍÑ}¡…¹•}…Ñ}Ù…±¥‘…Ñ•‘}¡•…¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰=Ý¹•ÉÍ¡¥À™½±±½ÝÌÑ¡”±¥Ù”¡•…‘•±…É…Ñ¥½¸É…Ñ¡•ÈÑ¡…¸ÍÑ…±”‰…Í”)M=8¸ˆˆˆ(€€€‘•Í­Ñ½À°‰…Í”€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ °l‰Á…­…•Ì¼¨‰t¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€ÑµÁ}Á…Ñ €¼€‰Á…­…”¹©Í½¸ˆ°(€€€€€€€ì‰¹…µ”ˆè€‰É½½Ðˆ°€‰ÁÉ¥Ù…Ñ”ˆèQÉÕ”°€‰Ý½É­ÍÁ…•Ìˆèl‰…ÁÁÌ¼¨ˆ°€‰Á…­…•Ì¼¨‰uô°(€€€€¤(€€€¡•…€ô}½µµ¥Ð¡ÑµÁ}Á…Ñ °€‰¡…¹”Ý½É­ÍÁ…•Ìˆ¤(€€€…ÍÍ•ÉÐ}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°‰…Í”°¡•…¤€ôô€ˆ¸ˆ(()‘•˜Ñ•ÍÑ}…•ÁÑÍ}ÁÉ}…‘‘•‘}Ý½É­ÍÁ…•}Á…­…•}¥¹}¡•…‘}±½­}µ…À¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰¹•ÜÝ½É­ÍÁ…”Á…­…”¥ÌÙ…±¥Ý¡•¸¡•…µ…¹¥™•ÍÐ…¹±½¬…É•”¸ˆˆˆ(€€€}¥¹¥Ñ}É•Á¼¡ÑµÁ}Á…Ñ ¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€ÑµÁ}Á…Ñ €¼€‰Á…­…”¹©Í½¸ˆ°(€€€€€€€ì‰¹…µ”ˆè€‰É½½Ðˆ°€‰ÁÉ¥Ù…Ñ”ˆèQÉÕ”°€‰Ý½É­ÍÁ…•Ìˆèl‰Á…­…•Ì¼¨‰uô°(€€€€¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€ÑµÁ}Á…Ñ €¼€‰Á…­…”µ±½¬¹©Í½¸ˆ°(€€€€€€€ì‰±½­™¥±•Y•ÉÍ¥½¸ˆè€Ì°€‰Á…­…•Ìˆèìˆˆèíõõô°(€€€€¤(€€€‰…Í”€ô}½µµ¥Ð¡ÑµÁ}Á…Ñ °€‰‰…Í”ˆ¤(€€€‘•Í­Ñ½À€ôÑµÁ}Á…Ñ €¼€‰…ÁÁÌˆ€¼€‰‘•Í­Ñ½Àˆ(€€€}ÝÉ¥Ñ•}©Í½¸¡‘•Í­Ñ½À€¼€‰Á…­…”¹©Í½¸ˆ°ì‰¹…µ”ˆè€‰‘•Í­Ñ½À‰ô¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€ÑµÁ}Á…Ñ €¼€‰Á…­…”¹©Í½¸ˆ°(€€€€€€€ì‰¹…µ”ˆè€‰É½½Ðˆ°€‰ÁÉ¥Ù…Ñ”ˆèQÉÕ”°€‰Ý½É­ÍÁ…•Ìˆèl‰…ÁÁÌ¼¨ˆ°€‰Á…­…•Ì¼¨‰uô°(€€€€¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€ÑµÁ}Á…Ñ €¼€‰Á…­…”µ±½¬¹©Í½¸ˆ°(€€€€€€€ì‰±½­™¥±•Y•ÉÍ¥½¸ˆè€Ì°€‰Á…­…•Ìˆèìˆˆèíô°€‰…ÁÁÌ½‘•Í­Ñ½Àˆèíõõô°(€€€€¤(€€€¡•…€ô}½µµ¥Ð¡ÑµÁ}Á…Ñ °€‰…‘Ý½É­ÍÁ…”ˆ¤(€€€…ÍÍ•ÉÐ}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°‰…Í”°¡•…¤€ôô€ˆ¸ˆ(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}Ý½É­ÑÉ••}±½­}Ñ¡…Ñ}‘¥™™•ÉÍ}™É½µ}Ù…±¥‘…Ñ•‘}¡•…¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰5ÕÑ…‰±”Ý½É­ÑÉ•”±½¬½¹Ñ•¹Ð…¹¹½ÐÉ•Á±…”Ñ¡”Ù…±¥‘…Ñ•¡•…‰±½ˆ¸ˆˆˆ(€€€‘•Í­Ñ½À°É•Ù¥Í¥½¸€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ ¤(€€€€¡ÑµÁ}Á…Ñ €¼€‰Á…­…”µ±½¬¹©Í½¸ˆ¤¹ÝÉ¥Ñ•}Ñ•áÐ ‰íõq¸ˆ°•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰‘½•Ì¹½Ðµ…Ñ Ñ¡”Ù…±¥‘…Ñ•¡•…ˆ¤è(€€€€€€€}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°É•Ù¥Í¥½¸¤(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}Ý½É­ÑÉ••}µ…¹¥™•ÍÑ}Ñ¡…Ñ}‘¥™™•ÉÍ}™É½µ}Ù…±¥‘…Ñ•‘}¡•… (€€€ÑµÁ}Á…Ñ èA…Ñ °(¤€´ø9½¹”è(€€€€ˆˆ‰5ÕÑ…‰±”Ý½É­ÑÉ•”µ…¹¥™•ÍÐ½¹Ñ•¹Ð…¹¹½Ð¥¹™±Õ•¹”½Ý¹•ÉÍ¡¥À¸ˆˆˆ(€€€‘•Í­Ñ½À°É•Ù¥Í¥½¸€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ ¤(€€€€¡ÑµÁ}Á…Ñ €¼€‰Á…­…”¹©Í½¸ˆ¤¹ÝÉ¥Ñ•}Ñ•áÐ ‰íõq¸ˆ°•¹½‘¥¹œô‰ÕÑ˜´àˆ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰‘½•Ì¹½Ðµ…Ñ Ñ¡”Ù…±¥‘…Ñ•¡•…ˆ¤è(€€€€€€€}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°É•Ù¥Í¥½¸¤(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}¥¹Ù…±¥‘}½É}µ¥ÍÍ¥¹}É•Ù¥Í¥½¸¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰=¹±ä•á…Ð•á¥ÍÑ¥¹œ½µµ¥ÐM!Ì…¸…¹¡½ÈÉ•Í½±Ù•È•Ù¥‘•¹”¸ˆˆˆ(€€€‘•Í­Ñ½À°É•Ù¥Í¥½¸€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ôˆÐÀ¡•á…‘•¥µ…°ˆ¤è(€€€€€€€}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°€‰µ…¥¸ˆ°É•Ù¥Í¥½¸¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰¥Ð…Ðµ™¥±”™…¥±•ˆ¤è(€€€€€€€}É•Í½±Ù”¡ÑµÁ}Á…Ñ °‘•Í­Ñ½À°€‰˜ˆ€¨€ÐÀ°É•Ù¥Í¥½¸¤(()‘•˜Ñ•ÍÑ}µ…¥¹}ÁÉ¥¹ÑÍ}É•Í½±Ù•‘}É½½Ð¡ÑµÁ}Á…Ñ èA…Ñ °…ÁÍåÌèÁåÑ•ÍÐ¹…ÁÑÕÉ•¥áÑÕÉ•mÍÑÉt¤€´ø9½¹”è(€€€€ˆˆ‰Q¡”½µµ…¹µ±¥¹”•¹ÑÉäÁ½¥¹ÐÁÉ¥¹ÑÌÑ¡”Ù…±¥‘…Ñ•¥¹ÍÑ…±°É½½Ð¸ˆˆˆ(€€€‘•Í­Ñ½À°É•Ù¥Í¥½¸€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ ¤(€€€…ÍÍ•ÉÐ€ (€€€€€€€µ½‘Õ±”¹µ…¥¸ (€€€€€€€€€€€l(€€€€€€€€€€€€€€€€ˆ´µÉ•Á¼µÉ½½Ðˆ°(€€€€€€€€€€€€€€€ÍÑÈ¡ÑµÁ}Á…Ñ ¤°(€€€€€€€€€€€€€€€€ˆ´µÁ…­…”µ‘¥Èˆ°(€€€€€€€€€€€€€€€ÍÑÈ¡‘•Í­Ñ½À¤°(€€€€€€€€€€€€€€€€ˆ´µ‰…Í”µÍ¡„ˆ°(€€€€€€€€€€€€€€€É•Ù¥Í¥½¸°(€€€€€€€€€€€€€€€€ˆ´µ¡•…µÍ¡„ˆ°(€€€€€€€€€€€€€€€É•Ù¥Í¥½¸°(€€€€€€€€€€€t(€€€€€€€€¤(€€€€€€€€ôô€À(€€€€¤(€€€…ÍÍ•ÉÐ…ÁÍåÌ¹É•…‘½ÕÑ•ÉÈ ¤¹½ÕÐ€ôô€ˆ¹q¸ˆ(()‘•˜Ñ•ÍÑ}µ…¥¹}É•Á½ÉÑÍ}É•Í½±ÕÑ¥½¹}•ÉÉ½È (€€€ÑµÁ}Á…Ñ èA…Ñ °…ÁÍåÌèÁåÑ•ÍÐ¹…ÁÑÕÉ•¥áÑÕÉ•mÍÑÉt(¤€´ø9½¹”è(€€€€ˆˆ‰Q¡”1$ÑÕÉ¹Ì™…¥°µ±½Í•É•Í½±Ù•È•ÉÉ½ÉÌ¥¹Ñ¼Á…ÉÍ•È•ÉÉ½ÉÌ¸ˆˆˆ(€€€‘•Í­Ñ½À°É•Ù¥Í¥½¸€ô}Ý½É­ÍÁ…”¡ÑµÁ}Á…Ñ ¤(€€€€¡ÑµÁ}Á…Ñ €¼€‰Á…­…”µ±½¬¹©Í½¸ˆ¤¹Õ¹±¥¹¬ ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡MåÍÑ•µá¥Ð°µ…Ñ ôˆÈˆ¤è(€€€€€€€µ½‘Õ±”¹µ…¥¸ (€€€€€€€€€€€l(€€€€€€€€€€€€€€€€ˆ´µÉ•Á¼µÉ½½Ðˆ°(€€€€€€€€€€€€€€€ÍÑÈ¡ÑµÁ}Á…Ñ ¤°(€€€€€€€€€€€€€€€€ˆ´µÁ…­…”µ‘¥Èˆ°(€€€€€€€€€€€€€€€ÍÑÈ¡‘•Í­Ñ½À¤°(€€€€€€€€€€€€€€€€ˆ´µ‰…Í”µÍ¡„ˆ°(€€€€€€€€€€€€€€€É•Ù¥Í¥½¸°(€€€€€€€€€€€€€€€€ˆ´µ¡•…µÍ¡„ˆ°(€€€€€€€€€€€€€€€É•Ù¥Í¥½¸°(€€€€€€€€€€€t(€€€€€€€€¤(€€€…ÍÍ•ÉÐ€‰É•Õ±…È¹½¸µÍåµ±¥¹¬™¥±”ˆ¥¸…ÁÍåÌ¹É•…‘½ÕÑ•ÉÈ ¤¹•ÉÈ(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}µ¥ÍÍ¥¹}Á…­…•}‘¥É•Ñ½Éä¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰¹½¹•á¥ÍÑ•¹ÐÍ•±•Ñ•Á…­…”Á…Ñ ™…¥±Ì‰•™½É”¥Ð•Ù¥‘•¹”¥ÌÉ•…¸ˆˆˆ(€€€É•Á¼€ôÑµÁ}Á…Ñ €¼€‰É•Á¼ˆ(€€€‘•Í­Ñ½À°É•Ù¥Í¥½¸€ô}Ý½É­ÍÁ…”¡É•Á¼¤(€€€µ¥ÍÍ¥¹œ€ô‘•Í­Ñ½À€¼€‰µ¥ÍÍ¥¹œˆ(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰‘½•Ì¹½Ð•á¥ÍÐˆ¤è(€€€€€€€}É•Í½±Ù”¡É•Á¼°µ¥ÍÍ¥¹œ°É•Ù¥Í¥½¸¤(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}µ¥ÍÍ¥¹}É•Á½Í¥Ñ½Éå}É½½Ð¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰¹½¹•á¥ÍÑ•¹ÐÉ•Á½Í¥Ñ½ÉäÉ½½Ð™…¥±ÌÝ¥Ñ „‰½Õ¹‘•É½½Ð‘¥…¹½ÍÑ¥Œ¸ˆˆˆ(€€€µ¥ÍÍ¥¹œ€ôÑµÁ}Á…Ñ €¼€‰µ¥ÍÍ¥¹œˆ(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰É•Á½Í¥Ñ½ÉäÉ½½Ðˆ¤è(€€€€€€€}É•Í½±Ù”¡µ¥ÍÍ¥¹œ°µ¥ÍÍ¥¹œ°€ˆÀˆ€¨€ÐÀ¤(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}±½­}½Ý¹•É}Ý¥Ñ¡½ÕÑ}µ…¹¥™•ÍÐ¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰±½¬…¹¹½Ð•ÍÑ…‰±¥Í ½Ý¹•ÉÍ¡¥ÀÝ¥Ñ¡½ÕÐ„É•Õ±…È½Ý¹•Èµ…¹¥™•ÍÐ¸ˆˆˆ(€€€É•Á¼€ôÑµÁ}Á…Ñ €¼€‰É•Á¼ˆ(€€€}¥¹¥Ñ}É•Á¼¡É•Á¼¤(€€€Á…­…”€ôÉ•Á¼€¼€‰…ÁÁÌˆ€¼€‰‘•Í­Ñ½Àˆ(€€€}ÝÉ¥Ñ•}©Í½¸¡Á…­…”€¼€‰Á…­…”¹©Í½¸ˆ°ì‰¹…µ”ˆè€‰‘•Í­Ñ½À‰ô¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€É•Á¼€¼€‰Á…­…”µ±½¬¹©Í½¸ˆ°(€€€€€€€ì‰±½­™¥±•Y•ÉÍ¥½¸ˆè€Ì°€‰Á…­…•Ìˆèì‰…ÁÁÌ½‘•Í­Ñ½Àˆèíõõô°(€€€€¤(€€€É•Ù¥Í¥½¸€ô}½µµ¥Ð¡É•Á¼¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰±½¬½Ý¹•Èµ…¹¥™•ÍÐˆ¤è(€€€€€€€}É•Í½±Ù”¡É•Á¼°Á…­…”°É•Ù¥Í¥½¸¤(()‘•˜Ñ•ÍÑ}É•©•ÑÍ}É½½Ñ}±½…±}±½­}Ý¥Ñ¡½ÕÑ}É½½Ñ}Á…­…•}•¹ÑÉä¡ÑµÁ}Á…Ñ èA…Ñ ¤€´ø9½¹”è(€€€€ˆˆ‰Á…­…”µ±½…°É½½Ð±½¬µÕÍÐ½Ù•È¥ÑÌ½Ý¸•µÁÑäÁ…­…”µµ…À­•ä¸ˆˆˆ(€€€É•Á¼€ôÑµÁ}Á…Ñ €¼€‰É•Á¼ˆ(€€€}¥¹¥Ñ}É•Á¼¡É•Á¼¤(€€€}ÝÉ¥Ñ•}©Í½¸¡É•Á¼€¼€‰Á…­…”¹©Í½¸ˆ°ì‰¹…µ”ˆè€‰É½½Ð‰ô¤(€€€}ÝÉ¥Ñ•}©Í½¸ (€€€€€€€É•Á¼€¼€‰Á…­…”µ±½¬¹©Í½¸ˆ°(€€€€€€€ì‰±½­™¥±•Y•ÉÍ¥½¸ˆè€Ì°€‰Á…­…•Ìˆèì‰½Ñ¡•Èˆèíõõô°(€€€€¤(€€€É•Ù¥Í¥½¸€ô}½µµ¥Ð¡É•Á¼¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ ô‰¹¼Ù…±¥‘…Ñ•Á…­…”µ±½¬ˆ¤è(€€€€€€€}É•Í½±Ù”¡É•Á¼°É•Á¼°É•Ù¥Í¥½¸¤(()ÁåÑ•ÍÐ¹µ…É¬¹Á…É…µ•ÑÉ¥é” (€€€€ ‰¥Ñ}½ÕÑÁÕÐˆ°€‰µ…Ñ ˆ¤°(€€€l(€€€€€€€€ (€€€€€€€€€€€ˆˆÄÀÀØÐÐ‰±½ˆ…………………………………………………………………………………………………qÑÁ…­…”¹©Í½¹pÀˆ(€€€€€€€€€€€ˆˆÄÀÀØÐÐ‰±½ˆ‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰‰qÑÁ…­…”¹©Í½¹pÀˆ°(€€€€€€€€€€€€‰µÕ±Ñ¥Á±”¥ÐÑÉ•”•¹ÑÉ¥•Ìˆ°(€€€€€€€€¤°(€€€€€€€€¡ˆ‰µ…±™½Éµ•‘qÑÁ…­…”¹©Í½¹pÀˆ°€‰µ…±™½Éµ•¥ÐÑÉ•”µ•Ñ…‘…Ñ„ˆ¤°(€€€€€€€€ (€€€€€€€€€€€ˆˆÄÀÀØÐÐ‰±½ˆ…………………………………………………………………………………………………………qÑ½Ñ¡•È¹©Í½¹pÀˆ°(€€€€€€€€€€€€‰Á…Ñ ‘¥¹½Ðµ…Ñ •á…Ñ±äˆ°(€€€€€€€€¤°(€€€€€€€€ (€€€€€€€€€€€ˆˆÄÈÀÀÀÀ‰±½ˆ…………………………………………………………………………………………………………qÑÁ…­…”¹©Í½¹pÀˆ°(€€€€€€€€€€€€‰É•Õ±…È¹½¸µÍåµ±¥¹¬¥Ð‰±½ˆˆ°(€€€€€€€€¤°(€€€t°(¤)‘•˜Ñ•ÍÑ}ÑÉ••}‰±½‰}É•©•ÑÍ}µ…±™½Éµ•‘}½É}Õ¹Í…™•}¥Ñ}µ•Ñ…‘…Ñ„ (€€€ÑµÁ}Á…Ñ èA…Ñ °(€€€µ½¹­•åÁ…Ñ èÁåÑ•ÍÐ¹5½¹­•åA…Ñ °(€€€¥Ñ}½ÕÑÁÕÐè‰åÑ•Ì°(€€€µ…Ñ èÍÑÈ°(¤€´ø9½¹”è(€€€€ˆˆ‰¥ÐÑÉ•”•Ù¥‘•¹”µÕÍÐ‰”Í¥¹Õ±…È°•á…Ð°…¹É•Õ±…Èµ™¥±”µ•Ñ…‘…Ñ„¸ˆˆˆ(€€€µ½¹­•åÁ…Ñ ¹Í•Ñ…ÑÑÈ¡µ½‘Õ±”°€‰}¥Ðˆ°±…µ‰‘„€©}…ÉÌè¥Ñ}½ÕÑÁÕÐ¤(€€€Ý¥Ñ ÁåÑ•ÍÐ¹É…¥Í•Ì¡I•Í½±ÕÑ¥½¹ÉÉ½È°µ…Ñ õµ…Ñ ¤è(€€€€€€€µ½‘Õ±”¹}ÑÉ••}‰±½ˆ (€€€€€€€€€€€ÑµÁ}Á…Ñ °(€€€€€€€€€€€€‰„ˆ€¨€ÐÀ°(€€€€€€€€€€€AÕÉ•A½Í¥áA…Ñ  ‰Á…­…”¹©Í½¸ˆ¤°(€€€€€€€€€€€€‰™¥áÑÕÉ”µ…¹¥™•ÍÐˆ°(€€€€€€€€¤(