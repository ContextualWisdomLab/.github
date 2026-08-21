"""Fail-closed contracts for the read-only workflow-lifecycle inventory."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import inventory_orphaned_workflows as inventory


SHA = "a" * 40
SHA_B = "b" * 40


def _workflow(
    workflow_id: int,
    path: str,
    *,
    state: str = "active",
    name: str | None = None,
) -> dict[str, Any]:
    """Return one GitHub Actions workflow registry record."""
    return {
        "id": workflow_id,
        "name": name or Path(path).name,
        "path": path,
        "state": state,
    }


def _repo(
    name: str,
    workflows: list[dict[str, Any]],
    tree_paths: list[str],
    *,
    archived: bool = False,
    sha: str = SHA,
    sha_after: str | None = None,
    pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one repository inventory fixture."""
    return {
        "name": name,
        "archived": archived,
        "default_branch": "main",
        "default_branch_sha": sha,
        "default_branch_sha_after": sha if sha_after is None else sha_after,
        "tree_paths": tree_paths,
        "workflow_pages": pages
        if pages is not None
        else [{"total_count": len(workflows), "workflows": workflows, "_link_next": False}],
    }


def _payload(repositories: list[dict[str, Any]]) -> dict[str, Any]:
    """Return an organization inventory fixture."""
    return {
        "organization": "ContextualWisdomLab",
        "observed_at": "2026-08-16T12:00:00Z",
        "repositories": repositories,
    }


def test_reject_forbidden_token_and_allow_unrelated_names() -> None:
    """Copilot tokens are forbidden; unrelated credential names are ignored."""
    inventory.reject_forbidden_token("NVIDIA_NIM_API_KEY")
    with pytest.raises(inventory.InventoryError, match="COPILOT_GITHUB_TOKEN"):
        inventory.reject_forbidden_token("COPILOT_GITHUB_TOKEN")


def test_refuse_registry_mutation() -> None:
    """Disablement stays on a separately reviewed operator path."""
    with pytest.raises(inventory.InventoryError, match="disable"):
        inventory.refuse_registry_mutation("disable")


def test_is_exact_sha() -> None:
    """Only a 40-character lowercase hex digest is a bound SHA."""
    assert inventory.is_exact_sha(SHA) is True
    assert inventory.is_exact_sha("A" * 40) is False
    assert inventory.is_exact_sha(1) is False
    assert inventory.is_exact_sha("deadbeef") is False


def test_parse_link_has_next() -> None:
    """Link pagination is boolean and fail-closed on malformed headers."""
    assert inventory.parse_link_has_next(None) is False
    assert inventory.parse_link_has_next('<https://example/page/2>; rel="next"') is True
    assert inventory.parse_link_has_next('<https://example/page/1>; rel="prev"') is False
    with pytest.raises(inventory.InventoryError, match="malformed"):
        inventory.parse_link_has_next("")
    with pytest.raises(inventory.InventoryError, match="malformed"):
        inventory.parse_link_has_next(1)


def test_decode_registry_path_rejects_encoding_and_traversal() -> None:
    """Percent-encoding, NULs, backslashes, and `..` fail closed."""
    assert (
        inventory.decode_registry_path(".github/workflows/ci.yml")
        == ".github/workflows/ci.yml"
    )
    with pytest.raises(inventory.InventoryError, match="NUL|missing"):
        inventory.decode_registry_path("")
    with pytest.raises(inventory.InventoryError, match="NUL|missing"):
        inventory.decode_registry_path(".github/workflows/ci.yml\x00")
    with pytest.raises(inventory.InventoryError, match="backslash"):
        inventory.decode_registry_path(".github\\workflows\\ci.yml")
    with pytest.raises(inventory.InventoryError, match="percent-encoded"):
        inventory.decode_registry_path(".github/workflows/%2e%2e/ci.yml")
    with pytest.raises(inventory.InventoryError, match="traversal"):
        inventory.decode_registry_path(".github/workflows/../../secret.yml")


def test_path_predicates() -> None:
    """Dynamic GitHub identities stay distinct from repository YAML files."""
    assert inventory.is_dynamic_owned_path("dynamic/pages/pages-build-deployment")
    assert inventory.is_repository_workflow_path(".github/workflows/ci.yml")
    assert inventory.is_repository_workflow_path(".github/workflows/ci.yaml")
    assert not inventory.is_repository_workflow_path(".GitHub/workflows/ci.yml")
    assert not inventory.is_repository_workflow_path(".github/workflows/nested/ci.yml")
    assert not inventory.is_repository_workflow_path(".github/workflows/ci.txt")
    assert not inventory.is_dynamic_owned_path(".github/workflows/ci.yml")


def test_interpret_status_and_single_retry() -> None:
    """Visibility loss and 5xx fail closed after at most one retry."""
    inventory.interpret_status(200, resource="workflows")
    with pytest.raises(inventory.InventoryError, match="permission"):
        inventory.interpret_status(401, resource="workflows")
    with pytest.raises(inventory.InventoryError, match="permission"):
        inventory.interpret_status(403, resource="workflows")
    with pytest.raises(inventory.InventoryError, match="missing visibility"):
        inventory.interpret_status(404, resource="workflows")
    with pytest.raises(inventory.InventoryError, match="transient"):
        inventory.interpret_status(503, resource="workflows")
    with pytest.raises(inventory.InventoryError, match="unexpected"):
        inventory.interpret_status(418, resource="workflows")

    calls = {"n": 0}

    def once_ok(url: str) -> tuple[int, dict[str, str], dict[str, str]]:
        calls["n"] += 1
        return 200, {"ok": url}, {"link": ""}

    body, headers = inventory.fetch_with_one_retry(once_ok, "https://example/ok")
    assert body == {"ok": "https://example/ok"}
    assert headers == {"link": ""}
    assert calls["n"] == 1

    def recover(url: str) -> tuple[int, dict[str, str], dict[str, str]]:
        calls["n"] += 1
        if calls["n"] == 2:
            return 503, {}, {}
        return 200, {"recovered": True}, {}

    calls["n"] = 1
    body, _headers = inventory.fetch_with_one_retry(recover, "https://example/retry")
    assert body == {"recovered": True}

    def stay_down(_url: str) -> tuple[int, dict[str, str], dict[str, str]]:
        return 500, {}, {}

    with pytest.raises(inventory.InventoryError, match="transient"):
        inventory.fetch_with_one_retry(stay_down, "https://example/down")


def test_classify_workflow_matrix() -> None:
    """Every advertised class is produced from path, state, and tree presence."""
    repo = ".github/workflows/ci.yml"
    assert (
        inventory.classify_workflow(
            path="dynamic/pages/pages-build-deployment",
            state="active",
            source_present=None,
        )
        == "dynamic_owned"
    )
    assert (
        inventory.classify_workflow(
            path=".GitHub/workflows/ci.yml",
            state="active",
            source_present=None,
        )
        == "unresolved"
    )
    assert (
        inventory.classify_workflow(path=repo, state="active", source_present=None)
        == "unresolved"
    )
    assert (
        inventory.classify_workflow(path=repo, state="active", source_present=True)
        == "present_active"
    )
    assert (
        inventory.classify_workflow(path=repo, state="active", source_present=False)
        == "orphan_active"
    )
    assert (
        inventory.classify_workflow(
            path=repo, state="disabled_manually", source_present=True
        )
        == "present_disabled"
    )
    assert (
        inventory.classify_workflow(
            path=repo, state="disabled_inactivity", source_present=False
        )
        == "orphan_disabled"
    )
    assert (
        inventory.classify_workflow(path=repo, state="mystery", source_present=True)
        == "unresolved"
    )


def test_collect_workflow_pages_fail_closed() -> None:
    """Partial pagination, drift, reuse, and empty next-pages fail closed."""
    first = {
        "total_count": 2,
        "workflows": [_workflow(1, ".github/workflows/a.yml")],
        "_link_next": True,
    }
    second = {
        "total_count": 2,
        "workflows": [_workflow(2, ".github/workflows/b.yml")],
        "_link_next": False,
    }
    assert len(inventory.collect_workflow_pages([first, second], per_page=1)) == 2

    with pytest.raises(inventory.InventoryError, match="per_page"):
        inventory.collect_workflow_pages([], per_page=0)
    with pytest.raises(inventory.InventoryError, match="no workflow pages"):
        inventory.collect_workflow_pages([])
    with pytest.raises(inventory.InventoryError, match="not an object"):
        inventory.collect_workflow_pages([None])  # type: ignore[list-item]
    with pytest.raises(inventory.InventoryError, match="workflows array"):
        inventory.collect_workflow_pages([{"total_count": 0}])
    with pytest.raises(inventory.InventoryError, match="total_count"):
        inventory.collect_workflow_pages([{"total_count": -1, "workflows": []}])
    with pytest.raises(inventory.InventoryError, match="drifted"):
        inventory.collect_workflow_pages(
            [
                {
                    "total_count": 2,
                    "workflows": [_workflow(1, ".github/workflows/a.yml")],
                    "_link_next": True,
                },
                {
                    "total_count": 3,
                    "workflows": [_workflow(2, ".github/workflows/b.yml")],
                    "_link_next": False,
                },
            ],
            per_page=1,
        )
    with pytest.raises(inventory.InventoryError, match="exceeds per_page"):
        inventory.collect_workflow_pages(
            [
                {
                    "total_count": 2,
                    "workflows": [
                        _workflow(1, ".github/workflows/a.yml"),
                        _workflow(2, ".github/workflows/b.yml"),
                    ],
                    "_link_next": False,
                }
            ],
            per_page=1,
        )
    with pytest.raises(inventory.InventoryError, match="not an object"):
        inventory.collect_workflow_pages(
            [{"total_count": 1, "workflows": ["bad"], "_link_next": False}]
        )
    with pytest.raises(inventory.InventoryError, match="truncated"):
        inventory.collect_workflow_pages(
            [
                {
                    "total_count": 2,
                    "workflows": [_workflow(1, ".github/workflows/a.yml")],
                    "_link_next": False,
                }
            ]
        )
    with pytest.raises(inventory.InventoryError, match="empty workflow page"):
        inventory.collect_workflow_pages(
            [{"total_count": 0, "workflows": [], "_link_next": True}]
        )
    with pytest.raises(inventory.InventoryError, match="truncated after last"):
        inventory.collect_workflow_pages(
            [
                {
                    "total_count": 1,
                    "workflows": [_workflow(1, ".github/workflows/a.yml")],
                    "_link_next": True,
                }
            ]
        )
    with pytest.raises(inventory.InventoryError, match="_link_next"):
        inventory.collect_workflow_pages(
            [{"total_count": 0, "workflows": [], "_link_next": "yes"}]
        )
    linked = {
        "total_count": 0,
        "workflows": [],
        "link": '<https://example/page/1>; rel="prev"',
    }
    assert inventory.collect_workflow_pages([linked]) == []
    with pytest.raises(inventory.InventoryError, match="reused workflow id"):
        inventory.collect_workflow_pages(
            [
                {
                    "total_count": 2,
                    "workflows": [
                        _workflow(7, ".github/workflows/a.yml"),
                        _workflow(7, ".github/workflows/renamed.yml"),
                    ],
                    "_link_next": False,
                }
            ]
        )
    with pytest.raises(inventory.InventoryError, match="positive integer"):
        inventory.collect_workflow_pages(
            [
                {
                    "total_count": 1,
                    "workflows": [{"id": "7", "path": ".github/workflows/a.yml"}],
                    "_link_next": False,
                }
            ]
        )


def test_assert_default_branch_bound() -> None:
    """A moved or malformed default-branch SHA aborts the inventory."""
    assert inventory.assert_default_branch_bound(SHA, SHA) == SHA
    with pytest.raises(inventory.InventoryError, match="moved"):
        inventory.assert_default_branch_bound(SHA, SHA_B)
    with pytest.raises(inventory.InventoryError, match="hex digest"):
        inventory.assert_default_branch_bound("main", "main")


def test_owner_issue_for_known_fleet() -> None:
    """Known fleet orphans route to the existing owner issues."""
    assert (
        inventory.owner_issue_for("appguardrail")
        == "ContextualWisdomLab/appguardrail#929"
    )
    assert inventory.owner_issue_for("naruon") == "ContextualWisdomLab/naruon#1324"


def test_owner_issue_registry_covers_confirmed_fleet() -> None:
    """Every confirmed fleet owner has an explicit, linkable issue route."""
    assert inventory.KNOWN_OWNER_ISSUES == {
        "appguardrail": "ContextualWisdomLab/appguardrail#929",
        "bandscope": "ContextualWisdomLab/bandscope#847",
        "clearfolio": "ContextualWisdomLab/clearfolio#423",
        "codec-carver": "ContextualWisdomLab/codec-carver#401",
        "contextual-orchestrator": "ContextualWisdomLab/contextual-orchestrator#122",
        "DiagramWeave": "ContextualWisdomLab/DiagramWeave#27",
        "disksage": "ContextualWisdomLab/disksage#191",
        "EgressWeave": "ContextualWisdomLab/EgressWeave#202",
        "fast-mlsirm": "ContextualWisdomLab/fast-mlsirm#809",
        "four-pillars": "ContextualWisdomLab/four-pillars#33",
        "inkspan": "ContextualWisdomLab/inkspan#278",
        "keyverse": "ContextualWisdomLab/keyverse#99",
        "naruon": "ContextualWisdomLab/naruon#1324",
        "newsdom-api": "ContextualWisdomLab/newsdom-api#604",
        "noema": "ContextualWisdomLab/noema#226",
        "OriginWeave": "ContextualWisdomLab/OriginWeave#123",
        "pg-erd-cloud": "ContextualWisdomLab/pg-erd-cloud#865",
        "RankWeave": "ContextualWisdomLab/RankWeave#38",
        "saju-caldav": "ContextualWisdomLab/saju-caldav#33",
        "ThreadWeave": "ContextualWisdomLab/ThreadWeave#31",
    }


def test_inventory_repository_classifies_known_shapes() -> None:
    """One-shot names, orphans, dynamic workflows, and archives stay honest."""
    result = inventory.inventory_repository(
        _repo(
            "clearfolio",
            [
                _workflow(1, ".github/workflows/one-shot-cleanup.yml"),
                _workflow(2, ".github/workflows/missing.yml"),
                _workflow(
                    3,
                    "dynamic/pages/pages-build-deployment",
                    name="pages",
                ),
                _workflow(
                    4,
                    ".github/workflows/old.yml",
                    state="disabled_manually",
                ),
            ],
            [".github/workflows/one-shot-cleanup.yml"],
        )
    )
    classes = {item["workflow_id"]: item["classification"] for item in result["records"]}
    assert classes[1] == "present_active"
    assert classes[2] == "orphan_active"
    assert classes[3] == "dynamic_owned"
    assert classes[4] == "orphan_disabled"
    orphan = next(item for item in result["records"] if item["workflow_id"] == 2)
    assert orphan["owner_issue"] == "ContextualWisdomLab/clearfolio#423"

    skipped = inventory.inventory_repository(_repo("old", [], [], archived=True))
    assert skipped["skipped"] == "archived"
    assert skipped["records"] == []


def test_inventory_routes_inkspan_orphan_to_owner_issue() -> None:
    """Inkspan orphan evidence reaches its confirmed central owner issue."""
    result = inventory.inventory_repository(
        _repo(
            "inkspan",
            [_workflow(20, ".github/workflows/apply-preparse-envelope-limits.yml")],
            [],
        )
    )
    assert result["records"][0]["classification"] == "orphan_active"
    assert result["records"][0]["owner_issue"] == "ContextualWisdomLab/inkspan#278"


def test_inventory_repository_rejects_malformed_records() -> None:
    """Malformed repository fixtures fail closed before classification."""
    with pytest.raises(inventory.InventoryError, match="valid slug"):
        inventory.inventory_repository(_repo("bad name", [], []))
    bad_flag = _repo("naruon", [], [])
    bad_flag["archived"] = "no"
    with pytest.raises(inventory.InventoryError, match="archived flag"):
        inventory.inventory_repository(bad_flag)
    bad_tree = _repo("naruon", [], [])
    bad_tree["tree_paths"] = [1]
    with pytest.raises(inventory.InventoryError, match="tree_paths"):
        inventory.inventory_repository(bad_tree)
    not_list = _repo("naruon", [], [])
    not_list["tree_paths"] = ".github/workflows/ci.yml"
    with pytest.raises(inventory.InventoryError, match="tree_paths"):
        inventory.inventory_repository(not_list)
    unnamed_orphan = inventory.inventory_repository(
        _repo(
            "unknown-repo",
            [_workflow(8, ".github/workflows/missing.yml")],
            [],
        )
    )
    assert unnamed_orphan["records"][0]["classification"] == "orphan_active"
    assert "owner_issue" not in unnamed_orphan["records"][0]
    bad_pages = _repo("naruon", [], [])
    bad_pages["workflow_pages"] = "pages"
    with pytest.raises(inventory.InventoryError, match="workflow_pages"):
        inventory.inventory_repository(bad_pages)
    present_disabled = inventory.inventory_repository(
        _repo(
            "naruon",
            [
                _workflow(
                    9,
                    ".github/workflows/ci.yml",
                    state="disabled_fork",
                )
            ],
            [".github/workflows/ci.yml"],
        )
    )
    assert present_disabled["records"][0]["classification"] == "present_disabled"
    unresolved = inventory.inventory_repository(
        _repo(
            "naruon",
            [_workflow(10, "not-a-workflow")],
            [],
        )
    )
    assert unresolved["records"][0]["classification"] == "unresolved"


def test_payload_loading_rejects_duplicates_and_bounds() -> None:
    """Empty, oversized, non-UTF-8, non-object, and duplicate-key payloads fail."""
    with pytest.raises(inventory.InventoryError, match="empty"):
        inventory.load_payload_bytes(b"")
    with pytest.raises(inventory.InventoryError, match="exceeds"):
        inventory.load_payload_bytes(b"{" + b"a" * (inventory.MAX_PAYLOAD_BYTES + 1))
    with pytest.raises(inventory.InventoryError, match="UTF-8"):
        inventory.load_payload_bytes(b"\xff")
    with pytest.raises(inventory.InventoryError, match="not JSON"):
        inventory.load_payload_bytes(b"{")
    with pytest.raises(inventory.InventoryError, match="JSON object"):
        inventory.load_payload_bytes(b"[]")
    with pytest.raises(inventory.InventoryError, match="duplicate object key"):
        inventory.reject_duplicate_keys([("a", 1), ("a", 2)])
    payload = inventory.load_payload_bytes(b'{"organization":"ContextualWisdomLab"}')
    assert payload["organization"] == "ContextualWisdomLab"


def test_inventory_organization_and_unknown_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Organization ledgers count classes and reject unknown ones."""
    payload = _payload(
        [
            _repo(
                "disksage",
                [_workflow(1, ".github/workflows/gone.yml")],
                [],
            )
        ]
    )
    ledger = inventory.inventory_organization(payload)
    assert ledger["schema_version"] == "1"
    assert ledger["assurance_posture"]["certification_claim"] is False
    assert ledger["assurance_posture"]["operational_pii_mask"] is False
    assert ledger["counts"]["orphan_active"] == 1
    assert ledger["records"][0]["owner_issue"] == "ContextualWisdomLab/disksage#191"

    with pytest.raises(inventory.InventoryError, match="organization"):
        inventory.inventory_organization({"organization": "other"})
    with pytest.raises(inventory.InventoryError, match="observed_at"):
        inventory.inventory_organization(
            {"organization": "ContextualWisdomLab", "observed_at": ""}
        )
    with pytest.raises(inventory.InventoryError, match="non-empty"):
        inventory.inventory_organization(
            {
                "organization": "ContextualWisdomLab",
                "observed_at": "2026-08-16T12:00:00Z",
                "repositories": [],
            }
        )
    with pytest.raises(inventory.InventoryError, match="not an object"):
        inventory.inventory_organization(
            {
                "organization": "ContextualWisdomLab",
                "observed_at": "2026-08-16T12:00:00Z",
                "repositories": ["naruon"],
            }
        )

    def lie(**_kwargs: object) -> str:
        return "not-a-class"

    monkeypatch.setattr(inventory, "classify_workflow", lie)
    with pytest.raises(inventory.InventoryError, match="unknown classification"):
        inventory.inventory_organization(
            _payload(
                [
                    _repo(
                        "naruon",
                        [_workflow(1, ".github/workflows/ci.yml")],
                        [".github/workflows/ci.yml"],
                    )
                ]
            )
        )


def test_write_ledger_and_main(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI writes a ledger, fails closed, and never mutates the registry."""
    payload = _payload(
        [
            _repo(
                "appguardrail",
                [
                    _workflow(1, ".github/workflows/apply-once.yml"),
                    _workflow(2, ".github/workflows/ci.yml"),
                ],
                [".github/workflows/ci.yml"],
            )
        ]
    )
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "ledger.json"
    assert (
        inventory.main(
            ["--payload", str(payload_path), "--output", str(output)]
        )
        == 0
    )
    ledger = json.loads(output.read_text(encoding="utf-8"))
    assert ledger["counts"]["orphan_active"] == 1
    assert ledger["counts"]["present_active"] == 1
    err = capsys.readouterr().err
    assert "PASS:" in err

    assert (
        inventory.main(
            ["--payload", str(payload_path), "--fail-on-orphan-active"]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "FAIL:" in captured.err
    assert '"schema_version"' in captured.out

    assert inventory.main(["--payload", str(payload_path), "--mutate", "disable"]) == 2
    assert "registry mutation" in capsys.readouterr().err

    missing = tmp_path / "missing.json"
    assert inventory.main(["--payload", str(missing)]) == 2
    assert "not found" in capsys.readouterr().err

    directory = tmp_path / "dir"
    directory.mkdir()
    assert inventory.main(["--payload", str(directory)]) == 2
    assert "unable to read payload" in capsys.readouterr().err

    payload_path.write_text("[]", encoding="utf-8")
    assert inventory.main(["--payload", str(payload_path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_main_reports_ledger_output_failures_separately(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI identifies an unwritable ledger path as an output failure."""
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(_payload([_repo("naruon", [], [])])), encoding="utf-8"
    )
    output = tmp_path / "missing" / "ledger.json"

    assert (
        inventory.main(
            ["--payload", str(payload_path), "--output", str(output)]
        )
        == 2
    )
    error = capsys.readouterr().err
    assert "unable to write ledger" in error
    assert "unable to read payload" not in error


def test_example_fixture_classifies_without_masking_identities() -> None:
    """The committed example ledger fixture is executable and unredacted."""
    raw = Path("schemas/examples/cwl-workflow-lifecycle-ledger-v1.example.json").read_bytes()
    ledger = inventory.inventory_organization(inventory.load_payload_bytes(raw))
    assert ledger["assurance_posture"]["operational_pii_mask"] is False
    classes = {item["path"]: item["classification"] for item in ledger["records"]}
    assert classes[".github/workflows/finalize-once.yml"] == "orphan_active"
    assert classes[".github/workflows/ci.yml"] == "present_active"
    assert classes["dynamic/pages/pages-build-deployment"] == "dynamic_owned"


def test_known_fleet_fixture_routes_owner_issues() -> None:
    """The three named fleet incidents remain routed, not heuristically deleted."""
    payload = _payload(
        [
            _repo(
                "appguardrail",
                [_workflow(11, ".github/workflows/finalize-once.yml")],
                [],
            ),
            _repo(
                "clearfolio",
                [_workflow(12, ".github/workflows/one-shot-repair.yml")],
                [".github/workflows/one-shot-repair.yml"],
            ),
            _repo(
                "disksage",
                [_workflow(13, ".github/workflows/pr-123-finalizer.yml")],
                [],
            ),
        ]
    )
    ledger = inventory.inventory_organization(payload)
    by_repo = {item["repository"]: item for item in ledger["records"]}
    assert by_repo["appguardrail"]["classification"] == "orphan_active"
    assert by_repo["appguardrail"]["owner_issue"] == (
        "ContextualWisdomLab/appguardrail#929"
    )
    assert by_repo["clearfolio"]["classification"] == "present_active"
    assert "owner_issue" not in by_repo["clearfolio"]
    assert by_repo["disksage"]["classification"] == "orphan_active"
    assert by_repo["disksage"]["owner_issue"] == "ContextualWisdomLab/disksage#191"
