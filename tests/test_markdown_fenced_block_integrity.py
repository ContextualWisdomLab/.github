"""Fenced code blocks in this repository's Markdown must survive conflict resolution.

No existing test parses fenced blocks. `ARCHITECTURE.md` — five mermaid diagrams
that are the control-plane drawing for review, hourly repair, SBOM attestation and
merge trust boundaries — is read by no test at all. So a merge or autofix conflict
resolution that splits one fenced block into two fragments ships green, and the
diagram source renders to readers as a plain code block.

Counting fences cannot catch that: a split leaves four fence lines where there were
two, so the count stays even and every block still "balances". These contracts key
on the shapes a split actually produces instead:

* a closing fence immediately followed by another fence, with nothing but blank
  lines between them (the seam where one block became two);
* a file that ends inside an unclosed block;
* an untagged block whose body reads as mermaid — the orphaned second half of a
  split ```mermaid block, which loses the tag because only the first fragment
  keeps the original opening line;
* a ```mermaid block whose body does not begin with a mermaid diagram keyword —
  the orphaned second half when the *tag* is what got duplicated.

The four negative controls at the end of this module prove the detectors fire:
each one splits a real `ARCHITECTURE.md` diagram the way a conflict resolution
would and asserts the matching helper reports it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Every mermaid diagram type used in this repository plus the rest of the
# documented set, so a new diagram kind is not reported as a split fragment.
MERMAID_KEYWORDS = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
    "quadrantChart",
    "requirementDiagram",
    "gitGraph",
    "mindmap",
    "timeline",
    "sankey-beta",
    "block-beta",
    "architecture-beta",
    "C4Context",
    "C4Container",
    "C4Component",
    "C4Dynamic",
    "C4Deployment",
    "%%{",  # an init directive may legitimately precede the diagram keyword
)

ARCHITECTURE = Path("ARCHITECTURE.md")
ARCHITECTURE_MERMAID_DIAGRAMS = 5


def _tracked_markdown_files() -> list[Path]:
    """List the Markdown files git tracks, so untracked scratch files are ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [Path(name) for name in listed.split("\0") if name]


def _fence_lines(text: str) -> list[tuple[int, str]]:
    """Return `(line number, info string)` for every fence line, in file order.

    A fence line is a line whose first non-space characters are three backticks.
    The info string is whatever follows them (``"mermaid"``, ``"bash"``, or ``""``
    for an untagged fence).
    """
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            found.append((number, stripped[3:].strip()))
    return found


def _blocks(text: str) -> list[tuple[int, str, list[str]]]:
    """Return `(opening line number, info string, body lines)` for each fenced block.

    Fences alternate opening/closing, which is how Markdown itself reads them, so
    the info string on a closing fence is reported by the caller rather than used
    here. A trailing unclosed block is omitted; `test_every_file_closes_its_blocks`
    is the contract that reports it.
    """
    lines = text.split("\n")
    fences = _fence_lines(text)
    blocks: list[tuple[int, str, list[str]]] = []
    for opening, closing in zip(fences[0::2], fences[1::2]):
        body = lines[opening[0] : closing[0] - 1]
        blocks.append((opening[0], opening[1], body))
    return blocks


def _first_content_line(body: list[str]) -> str:
    """Return the first non-blank line of a block body, or the empty string."""
    for line in body:
        if line.strip():
            return line.strip()
    return ""


# A mermaid node declaration with a quoted label — `Hub["This repo"]`,
# `Gate{"approved?"}`, `Run("strix")`. The quotes are what make this safe to
# match: the shell, JSON and log output this repository otherwise fences does
# not put a quoted string inside brackets immediately after a bare identifier.
MERMAID_NODE = re.compile(r'^\w[\w.-]*[\[({]"[^"]*"[\])}]$')


def _reads_as_mermaid(body: list[str]) -> bool:
    """Report whether a block body looks like mermaid diagram source.

    Used to spot the orphaned half of a split ```mermaid block, which keeps the
    diagram text but loses the language tag. A fragment can begin at any line of
    the original diagram, so this matches the three shapes a mermaid line takes:
    the opening diagram keyword, an edge, and a quoted node declaration.
    """
    first = _first_content_line(body)
    if first.startswith(MERMAID_KEYWORDS) or first.startswith("subgraph "):
        return True
    if any(edge in first for edge in ("-->", "-.->", "==>", "---|")):
        return True
    return bool(MERMAID_NODE.match(first))


def _unclosed_files(paths: list[Path]) -> list[str]:
    """Return a report line for every file that ends inside a fenced block."""
    return [
        f"{path}: file ends inside an unclosed fenced block"
        for path in paths
        if len(_fence_lines(path.read_text(encoding="utf-8"))) % 2
    ]


def _adjacent_fence_seams(text: str, path: Path) -> list[str]:
    """Return a report line for each closing fence directly followed by a new fence.

    This is the seam a split leaves behind: the inserted closing fence and the
    inserted opening fence end up next to each other, separated at most by blank
    lines. Two genuinely separate blocks in this repository always have prose,
    a heading or a list item between them.
    """
    lines = text.split("\n")
    fences = _fence_lines(text)
    seams: list[str] = []
    for closing, following in zip(fences[1::2], fences[2::2]):
        between = lines[closing[0] : following[0] - 1]
        if all(not line.strip() for line in between):
            seams.append(
                f"{path}:{closing[0]}-{following[0]}: a block closes and another "
                "opens with nothing between them, the shape a split block leaves"
            )
    return seams


def test_every_file_closes_its_blocks() -> None:
    """Every tracked Markdown file must end outside a fenced block."""
    assert _unclosed_files(_tracked_markdown_files()) == []


def test_no_block_closes_and_reopens_with_nothing_between() -> None:
    """No tracked Markdown file may carry the seam a split fenced block leaves."""
    seams: list[str] = []
    for path in _tracked_markdown_files():
        seams += _adjacent_fence_seams(path.read_text(encoding="utf-8"), path)
    assert seams == []


def test_no_untagged_block_reads_as_mermaid() -> None:
    """An untagged block holding mermaid source is an orphaned diagram fragment."""
    orphans: list[str] = []
    for path in _tracked_markdown_files():
        for line_number, info, body in _blocks(path.read_text(encoding="utf-8")):
            if not info and _reads_as_mermaid(body):
                orphans.append(
                    f"{path}:{line_number}: untagged fenced block reads as mermaid "
                    f"source ({_first_content_line(body)!r})"
                )
    assert orphans == []


def test_every_mermaid_block_starts_with_a_diagram_keyword() -> None:
    """A ```mermaid block must open with a mermaid diagram keyword, not a fragment."""
    bad: list[str] = []
    for path in _tracked_markdown_files():
        for line_number, info, body in _blocks(path.read_text(encoding="utf-8")):
            if info != "mermaid":
                continue
            first = _first_content_line(body)
            if not first.startswith(MERMAID_KEYWORDS):
                bad.append(
                    f"{path}:{line_number}: mermaid block starts with {first!r}, "
                    "not a mermaid diagram keyword"
                )
    assert bad == []


def test_architecture_diagrams_are_all_present_and_tagged() -> None:
    """`ARCHITECTURE.md`'s five control-plane diagrams stay five tagged mermaid blocks.

    This file is the one no other test reads, and a lost tag degrades a diagram to
    a code listing without failing anything else.
    """
    blocks = _blocks(ARCHITECTURE.read_text(encoding="utf-8"))
    mermaid = [block for block in blocks if block[1] == "mermaid"]
    assert len(mermaid) == ARCHITECTURE_MERMAID_DIAGRAMS
    assert len(blocks) == ARCHITECTURE_MERMAID_DIAGRAMS


# --- negative controls -------------------------------------------------------
#
# Each builds the exact damage a conflict resolution produces and asserts the
# matching helper reports it, so a detector that silently stopped matching fails
# here rather than passing the whole suite on an intact tree.


def _first_diagram_opening(text: str) -> int:
    """Return the zero-based index of the first ```mermaid line."""
    lines = text.split("\n")
    return next(index for index, line in enumerate(lines) if line.strip() == "```mermaid")


def _first_diagram_body_length(text: str) -> int:
    """Return how many body lines the first ```mermaid block holds."""
    lines = text.split("\n")
    opening = _first_diagram_opening(text)
    closing = next(
        index
        for index, line in enumerate(lines)
        if index > opening and line.strip() == "```"
    )
    return closing - opening - 1


def _split_first_diagram(
    text: str, *, keep_tag: bool, after_body_line: int = 1
) -> str:
    """Split the first ```mermaid block in two, the way a bad resolution does.

    A closing fence and a new opening fence are inserted after `after_body_line`
    body lines. `keep_tag` chooses which half keeps the ``mermaid`` info string:
    ``False`` reproduces the common case where the second half becomes untagged,
    ``True`` the case where the tag is duplicated onto a fragment.
    """
    lines = text.split("\n")
    seam = _first_diagram_opening(text) + 1 + after_body_line
    reopened = "```mermaid" if keep_tag else "```"
    return "\n".join(lines[:seam] + ["```", reopened] + lines[seam:])


def test_split_block_is_reported_as_a_seam(tmp_path: Path) -> None:
    """A split diagram must be reported by the closes-and-reopens contract.

    This is the position-independent detector: it holds at every split point,
    including the last body line, where the orphaned fragment is empty and the
    content-shape detectors have nothing to match.
    """
    text = ARCHITECTURE.read_text(encoding="utf-8")
    missed = [
        offset
        for offset in range(1, _first_diagram_body_length(text) + 1)
        if not _adjacent_fence_seams(
            _split_first_diagram(text, keep_tag=False, after_body_line=offset),
            tmp_path / "ARCHITECTURE.md",
        )
    ]
    assert missed == []


def test_split_block_orphan_is_reported_as_untagged_mermaid() -> None:
    """The untagged half of a split diagram must read as an orphaned fragment.

    Checked at every split point that leaves two non-empty fragments, not one
    convenient offset: a real resolution splits wherever the conflict landed, and
    the first draft of this detector only recognised a fragment that began on the
    diagram's keyword line. The one excluded split point is the last body line,
    whose second fragment is empty and so cannot read as anything;
    `test_split_block_is_reported_as_a_seam` is what covers that case, and does.
    """
    text = ARCHITECTURE.read_text(encoding="utf-8")
    missed = []
    for offset in range(1, _first_diagram_body_length(text)):
        damaged = _split_first_diagram(text, keep_tag=False, after_body_line=offset)
        if not [
            body
            for _, info, body in _blocks(damaged)
            if not info and _reads_as_mermaid(body)
        ]:
            missed.append(offset)
    assert missed == []


def test_split_block_keeping_the_tag_is_reported_as_a_fragment() -> None:
    """A re-tagged fragment must fail the diagram-keyword contract."""
    damaged = _split_first_diagram(
        ARCHITECTURE.read_text(encoding="utf-8"), keep_tag=True
    )
    fragments = [
        _first_content_line(body)
        for _, info, body in _blocks(damaged)
        if info == "mermaid" and not _first_content_line(body).startswith(MERMAID_KEYWORDS)
    ]
    assert fragments != []


def test_unclosed_block_is_reported(tmp_path: Path) -> None:
    """A file left inside an open block must be reported by the balance contract."""
    damaged = tmp_path / "unclosed.md"
    damaged.write_text("# Title\n\n```mermaid\ngraph TD\n  A --> B\n", encoding="utf-8")
    assert _unclosed_files([damaged]) != []
