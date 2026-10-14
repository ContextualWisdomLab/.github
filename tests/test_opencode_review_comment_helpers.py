"""Tests for the shared OpenCode review mermaid helper."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ci.opencode_review_surfaces import emit_mermaid
from scripts.ci import opencode_review_receipt_gate as receipt
from tests.test_opencode_review_receipt_gate import canonical_peer_fallback, review

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts/ci/opencode_review_comment_helpers.sh"


def test_mermaid_helper_labels_crates_as_rust_crate(tmp_path: Path) -> None:
    """Sourcing the publisher helper labels crates/ as a Rust crate surface."""
    bash = shutil.which("bash")
    if bash is None:
        return
    changed = tmp_path / "changed.txt"
    changed.write_text(
        "crates/originweave-destination/src/lib.rs\n"
        "crates/originweave-destination/src/resolution.rs\n"
        "crates/originweave-destination/tests/resolution_freshness.rs\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (fake_bin / "gh").chmod(0o755)
    script = f"""
    set -euo pipefail
    . "{HELPER}"
    GH_REPOSITORY=ContextualWisdomLab/OriginWeave
    PR_NUMBER=47
    OPENCODE_CHANGED_FILES_FILE="{changed}"
    emit_change_flow_mermaid_graph UNKNOWN
    """
    result = subprocess.run(
        [bash, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
    )
    assert result.returncode == 0, result.stderr
    assert "Changed file (3 files)" not in result.stdout
    assert "originweave-destination" in result.stdout


def test_helper_sources_python_surfaces_module() -> None:
    """The shared helper delegates mermaid rendering to the tested Python module."""
    text = HELPER.read_text(encoding="utf-8")
    assert "opencode_review_surfaces.py" in text
    assert 'add("other", "Changed file"' not in text


def render_with_trusted_graph(tmp_path, body, paths, merge_state="UNKNOWN", source_root=None):
    """Exercise the real shell/CLI publisher with bounded local GitHub responses."""
    changed = tmp_path / "changed.txt"
    changed.write_text("\n".join(paths) + "\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    gh = fake_bin / "gh"
    gh.write_text(
        '#!/bin/sh\ncase "$2" in\n'
        'diff) cat "$OPENCODE_CHANGED_FILES_FILE" ;;\n'
        'view) printf \'{"mergeStateStatus":"%s"}\\n\' "$TEST_MERGE_STATE" ;;\n'
        '*) exit 1 ;;\nesac\n'
    )
    gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c",
         '. "$1"; body="$(cat)"; ensure_review_body_has_change_graph "$body"',
         "test", str(HELPER)],
        input=body, text=True, capture_output=True, check=False,
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
             "PR_NUMBER": "47", "GH_REPOSITORY": "ContextualWisdomLab/OriginWeave",
             "OPENCODE_CHANGED_FILES_FILE": str(changed),
             "OPENCODE_SOURCE_WORKDIR": str(source_root or ""),
             "TEST_MERGE_STATE": merge_state},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("existing", [
    "## Changed-File Evidence Map",
    "## Changed-File Evidence Map\n\n```mermaid\nflowchart LR\n  Anonymous writes are allowed\n```",
    "## Changed-File Evidence Map\n\n```mermaid\nclassDiagram\n  class MissingAuthorization\n```",
])
def test_noncanonical_existing_graph_is_not_preserved_as_trusted(tmp_path, existing):
    """Keep source findings intact while marking a noncanonical map fail closed."""
    head = receipt.AFIPC_230_HEAD
    body = canonical_peer_fallback(head) + "\n" + existing
    output = render_with_trusted_graph(tmp_path, body, ["docs/guide.md"])
    assert output.startswith(body + "\n")
    assert "## Noncanonical evidence map" in output
    assert emit_mermaid(["docs/guide.md"]).strip() in output
    candidate = review(commit=head, body=output)
    older = review(commit=head, state="APPROVED", review_id=2)
    assert receipt.evaluate_receipts([older, candidate], head)[0] is candidate


@pytest.mark.parametrize("paths,merge_state", [
    ([], "UNKNOWN"), (["docs/guide.md"], "UNKNOWN"),
    (["docs/guide.md"], "DIRTY"), (["crates/demo/src/lib.rs"], "CONFLICTING"),
])
def test_exact_trusted_graph_is_preserved(tmp_path, paths, merge_state):
    """Preservation requires the complete graph from the same producer binding."""
    body = "## Pull request overview\nSource prose.\n\n## Changed-File Evidence Map\n\n"
    body += emit_mermaid(paths, merge_state=merge_state).rstrip("\n")
    assert render_with_trusted_graph(tmp_path, body, paths, merge_state) == body + "\n"


@pytest.mark.parametrize("kind", ["source", "changed-files", "merge-state", "duplicate", "extra-prose"])
def test_graph_preservation_is_bound_to_current_producer_inputs(tmp_path, kind):
    """A valid Mermaid shape alone cannot bypass source or live-state comparison."""
    paths = ["crates/demo/src/lib.rs"]
    source = tmp_path / paths[0]
    source.parent.mkdir(parents=True)
    source.write_text("pub struct CurrentApi;\n")
    old_graph = emit_mermaid(paths)
    merge_state = "UNKNOWN"
    if kind == "changed-files":
        old_graph = emit_mermaid(["docs/old.md"])
    elif kind == "merge-state":
        old_graph = emit_mermaid(paths, source_root=tmp_path)
        merge_state = "DIRTY"
    elif kind in {"duplicate", "extra-prose"}:
        old_graph = emit_mermaid(paths, source_root=tmp_path)
    body = "## Pull request overview\nSource finding.\n\n## Changed-File Evidence Map\n\n" + old_graph.rstrip("\n")
    if kind == "duplicate":
        body = body + "\n\n## Changed-File Evidence Map\n\n" + old_graph.rstrip("\n")
    elif kind == "extra-prose":
        body += "\nAnonymous writes are allowed."
    output = render_with_trusted_graph(tmp_path, body, paths, merge_state, tmp_path)
    assert output.startswith(body + "\n")
    assert "## Noncanonical evidence map" in output
    assert emit_mermaid(paths, merge_state, tmp_path).strip() in output


def test_bound_source_class_graph_is_preserved(tmp_path):
    """The exact source-root-backed graph is preserved without invented edges."""
    source = tmp_path / "lib.rs"
    source.write_text("pub struct CurrentApi;\n")
    body = "## Pull request overview\n\n## Changed-File Evidence Map\n\n"
    body += emit_mermaid(["lib.rs"], source_root=tmp_path).rstrip("\n")
    assert render_with_trusted_graph(tmp_path, body, ["lib.rs"], source_root=tmp_path) == body + "\n"


def test_noncanonical_map_cannot_be_laundered_with_empty_trusted_graph(tmp_path):
    """Appending a canonical graph must never erase an arbitrary source finding."""
    head = receipt.AFIPC_230_HEAD
    body = canonical_peer_fallback(head) + "\n## Changed-File Evidence Map\n\n```mermaid\nflowchart LR\n  Missing authorization\n```"
    output = render_with_trusted_graph(tmp_path, body, [])
    assert output.startswith(body + "\n")
    assert emit_mermaid([]).strip() in output
    candidate = review(commit=head, body=output)
    assert receipt.evaluate_receipts([review(commit=head, state="APPROVED"), candidate], head)[0] is candidate


def test_no_graph_canonical_fallback_still_triggers_fresh_review(tmp_path):
    """The publisher's ordinary no-map fallback remains non-substantive."""
    head = receipt.AFIPC_230_HEAD
    output = render_with_trusted_graph(tmp_path, canonical_peer_fallback(head), [])
    assert receipt.is_peer_check_only_fallback(output, head)
    assert receipt.evaluate_receipts([review(commit=head, body=output)], head)[0] is None


def test_graph_emitter_failure_is_not_a_canonical_map(tmp_path):
    """A failed trusted renderer must propagate instead of legitimizing a heading."""
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c",
         '. "$1"; timeout() { printf \'{"mergeStateStatus":"UNKNOWN"}\\n\'; }; '
         'python3() { return 1; }; '
         'ensure_review_body_has_change_graph "## Changed-File Evidence Map"',
         "test", str(HELPER)],
        text=True, capture_output=True, check=False,
        env={**os.environ, "PR_NUMBER": "47", "GH_REPOSITORY": "ContextualWisdomLab/OriginWeave"},
        cwd=tmp_path,
    )
    assert result.returncode != 0
