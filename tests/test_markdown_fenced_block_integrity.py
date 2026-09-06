"""Fenced code blocks in this repository's Markdown must survive conflict resolution.

No other test parses fenced blocks. `ARCHITECTURE.md` — five mermaid diagrams that
are the control-plane drawing for review, hourly repair, SBOM attestation and merge
trust boundaries — is read by no test at all. So a merge or autofix conflict
resolution that splits one fenced block into two fragments ships green, and the
diagram source renders to readers as a plain code block.

Counting fences cannot catch that: a split leaves four fence lines where there were
two, so the count stays even and every block still "balances". Worse, a parity count
is wrong in its own right — per CommonMark a closing fence carries no info string,
so ```` ```bash ```` … ```` ```python ```` … EOF is *one unclosed block* whose second
tagged line is content, while a parity count reads it as two balanced fences and
lets the rest of the document render inside the open block. `_parse_blocks` is
therefore a state machine over opener length and info string, not a counter.

The contracts key on the shapes a split actually produces:

* a block that closes and another that opens with nothing but blank lines between
  them (the seam) — position-independent, the primary detector;
* a file that ends inside an unclosed block;
* an untagged block whose body reads as mermaid — the orphaned second half, which
  loses the tag because only the first fragment keeps the original opening line;
* a ```mermaid block whose body does not begin with a mermaid diagram declaration —
  the orphan when the *tag* is what got duplicated.

The negative controls at the end prove each detector fires, at every split point
rather than one convenient offset.
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
)

# A declaration must be the keyword itself, not merely start with it:
# `"graphical nonsense".startswith("graph")` is True, and such a block does not
# render. Longest alternative first so `stateDiagram-v2` is not truncated to
# `stateDiagram`, and the lookahead rejects any identifier character after it.
MERMAID_DECLARATION = re.compile(
    "^(?:%s)(?![A-Za-z0-9_-])"
    % "|".join(re.escape(word) for word in sorted(MERMAID_KEYWORDS, key=len, reverse=True))
)

# A mermaid node declaration with a quoted label — `Hub["This repo"]`,
# `Gate{"approved?"}`, `Run("strix")`. The quotes are what make this safe to
# match: the shell, JSON and log output this repository otherwise fences does not
# put a quoted string inside brackets immediately after a bare identifier.
MERMAID_NODE = re.compile(r'^\w[\w.-]*[\[({]"[^"]*"[\])}]$')

MERMAID_EDGES = ("-->", "-.->", "==>", "---|")

ARCHITECTURE = Path("ARCHITECTURE.md")
ARCHITECTURE_MERMAID_DIAGRAMS = 5
QUALITY_WORKFLOW = Path(".github/workflows/markdown-fenced-block-quality-ci.yml")
# GitHub documents `**.md` as "every Markdown file in the repository"; the
# `**/*.md` spelling is ambiguous about root-level files, and ARCHITECTURE.md --
# the whole reason this contract exists -- is one.
MARKDOWN_GLOB = "**.md"


def _tracked_markdown_files() -> list[Path]:
    """List the Markdown files git tracks, so untracked scratch files are ignored."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [Path(name) for name in listed.split("\0") if name]


def _fence(line: str) -> tuple[str, int, str] | None:
    """Return `(delimiter, run length, info string)` if this line is a fence.

    CommonMark supports both backtick and tilde fences, and a block opened with
    one delimiter is closed only by the other of the same kind — so the delimiter
    travels with the run length rather than being assumed to be a backtick.
    """
    stripped = line.strip()
    for delimiter in ("`", "~"):
        if stripped.startswith(delimiter * 3):
            run = len(stripped) - len(stripped.lstrip(delimiter))
            return delimiter, run, stripped[run:].strip()
    return None


def _parse_blocks(text: str) -> list[tuple[int, str, list[str], int | None]]:
    """Return `(opening line, info string, body lines, closing line)` per block.

    A state machine rather than a pairing of alternate fence lines, because
    CommonMark closes a block only on a fence that carries **no** info string and
    is at least as long as the opener. A tagged fence encountered while a block is
    open is that block's content — the case a parity count silently mis-pairs.
    `closing line` is `None` for a block the file never closes.
    """
    lines = text.split("\n")
    blocks: list[tuple[int, str, list[str], int | None]] = []
    opening: int | None = None
    info = ""
    delimiter = ""
    run = 0
    for number, line in enumerate(lines, 1):
        parsed = _fence(line)
        if parsed is None:
            continue
        line_delimiter, line_run, line_info = parsed
        if opening is None:
            opening, info, delimiter, run = number, line_info, line_delimiter, line_run
        elif line_delimiter == delimiter and not line_info and line_run >= run:
            blocks.append((opening, info, lines[opening : number - 1], number))
            opening = None
    if opening is not None:
        blocks.append((opening, info, lines[opening:], None))
    return blocks


def _declaration_line(body: list[str]) -> str:
    """Return a block body's first line that is neither blank nor a mermaid comment.

    Mermaid ignores any `%%`-prefixed line — both an ordinary `%% explanation`
    comment and a `%%{init: …}%%` directive — and renders the declaration that
    follows, so an annotated diagram must be read past them rather than rejected.
    """
    for line in body:
        stripped = line.strip()
        if stripped and not stripped.startswith("%%"):
            return stripped
    return ""


def _reads_as_mermaid(body: list[str]) -> bool:
    """Report whether a block body looks like mermaid diagram source.

    Used to spot the orphaned half of a split ```mermaid block, which keeps the
    diagram text but loses the language tag. A fragment can begin at any line of
    the original diagram, so this matches the three shapes a mermaid line takes:
    the opening declaration, an edge, and a quoted node declaration.
    """
    first = _declaration_line(body)
    if MERMAID_DECLARATION.match(first) or first.startswith("subgraph "):
        return True
    if any(edge in first for edge in MERMAID_EDGES):
        return True
    return bool(MERMAID_NODE.match(first))


def _unclosed_blocks(path: Path, text: str) -> list[str]:
    """Return a report line for every block in this file the text never closes."""
    return [
        f"{path}:{opening}: fenced block opened here is never closed by an "
        "untagged fence of the same delimiter and at least the same length"
        for opening, _, _, closing in _parse_blocks(text)
        if closing is None
    ]


def _adjacent_fence_seams(text: str, path: Path) -> list[str]:
    """Return a report line for each block that closes where the next one opens.

    This is the seam a split leaves behind: the inserted closing fence and the
    inserted opening fence end up next to each other, separated at most by blank
    lines. Two genuinely separate blocks in this repository always have prose, a
    heading or a list item between them.
    """
    lines = text.split("\n")
    blocks = _parse_blocks(text)
    seams: list[str] = []
    for (_, _, _, closing), (opening, _, _, _) in zip(blocks, blocks[1:]):
        if closing is None:
            continue
        if all(not line.strip() for line in lines[closing : opening - 1]):
            seams.append(
                f"{path}:{closing}-{opening}: a block closes and another opens "
                "with nothing between them, the shape a split block leaves"
            )
    return seams


def test_every_file_closes_its_blocks() -> None:
    """Every tracked Markdown file must end outside a fenced block."""
    unclosed: list[str] = []
    for path in _tracked_markdown_files():
        unclosed += _unclosed_blocks(path, path.read_text(encoding="utf-8"))
    assert unclosed == []


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
        for opening, info, body, _ in _parse_blocks(path.read_text(encoding="utf-8")):
            if not info and _reads_as_mermaid(body):
                orphans.append(
                    f"{path}:{opening}: untagged fenced block reads as mermaid "
                    f"source ({_declaration_line(body)!r})"
                )
    assert orphans == []


def test_every_mermaid_block_starts_with_a_diagram_declaration() -> None:
    """A ```mermaid block must declare a diagram type, not open on a fragment."""
    bad: list[str] = []
    for path in _tracked_markdown_files():
        for opening, info, body, _ in _parse_blocks(path.read_text(encoding="utf-8")):
            if info != "mermaid":
                continue
            first = _declaration_line(body)
            if not MERMAID_DECLARATION.match(first):
                bad.append(
                    f"{path}:{opening}: mermaid block declares {first!r}, "
                    "not a mermaid diagram type"
                )
    assert bad == []


def test_architecture_diagrams_are_all_present_and_tagged() -> None:
    """`ARCHITECTURE.md`'s five control-plane diagrams stay five tagged mermaid blocks.

    This file is the one no other test reads, and a lost tag degrades a diagram to
    a code listing without failing anything else.
    """
    blocks = _parse_blocks(ARCHITECTURE.read_text(encoding="utf-8"))
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


def _split_first_diagram(text: str, *, keep_tag: bool, after_body_line: int = 1) -> str:
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
    diagram's declaration line. The one excluded split point is the last body
    line, whose second fragment is empty and so cannot read as anything;
    `test_split_block_is_reported_as_a_seam` is what covers that case, and does.
    """
    text = ARCHITECTURE.read_text(encoding="utf-8")
    missed = []
    for offset in range(1, _first_diagram_body_length(text)):
        damaged = _split_first_diagram(text, keep_tag=False, after_body_line=offset)
        if not [
            body
            for _, info, body, _ in _parse_blocks(damaged)
            if not info and _reads_as_mermaid(body)
        ]:
            missed.append(offset)
    assert missed == []


def test_split_block_keeping_the_tag_is_reported_as_a_fragment() -> None:
    """A re-tagged fragment must fail the diagram-declaration contract."""
    damaged = _split_first_diagram(
        ARCHITECTURE.read_text(encoding="utf-8"), keep_tag=True
    )
    fragments = [
        _declaration_line(body)
        for _, info, body, _ in _parse_blocks(damaged)
        if info == "mermaid" and not MERMAID_DECLARATION.match(_declaration_line(body))
    ]
    assert fragments != []


def test_unclosed_block_is_reported(tmp_path: Path) -> None:
    """A file left inside an open block must be reported by the balance contract."""
    text = "# Title\n\n```mermaid\ngraph TD\n  A --> B\n"
    assert _unclosed_blocks(tmp_path / "unclosed.md", text) != []


def test_a_tagged_fence_does_not_close_an_open_block(tmp_path: Path) -> None:
    """A second tagged fence is block content, so the first block stays unclosed.

    CommonMark closes a fenced block only on a fence with no info string, so
    ```` ```bash ```` … ```` ```python ```` … EOF is one unclosed block whose
    second tagged line is content. An even-fence-count check reads it as two
    balanced blocks and reports nothing, which is why `_parse_blocks` tracks
    opener state instead of pairing alternate fence lines.
    """
    text = "```bash\necho one\n```python\nprint('two')\n"
    blocks = _parse_blocks(text)
    assert len(blocks) == 1
    assert blocks[0][1] == "bash"
    assert blocks[0][3] is None
    assert _unclosed_blocks(tmp_path / "mixed.md", text) != []


def test_a_shorter_untagged_fence_does_not_close_a_longer_block() -> None:
    """A three-backtick line inside a four-backtick block is content, not a close."""
    text = "````markdown\n```\nnested sample\n```\n````\n"
    blocks = _parse_blocks(text)
    assert len(blocks) == 1
    assert blocks[0][1] == "markdown"
    assert blocks[0][3] == 5


def test_a_commented_mermaid_block_declares_its_diagram() -> None:
    """A `%%` comment or init directive before the declaration must not fail the check.

    Mermaid ignores `%%` lines and renders what follows, so reading only the first
    non-blank line rejects an ordinary annotated diagram. Both comment forms are
    checked because the init directive shares the prefix.
    """
    commented = ["%% why this diagram exists", "", "flowchart LR", '  A["a"] --> B']
    directive = ["%%{init: {'theme': 'dark'}}%%", "sequenceDiagram", "  A->>B: hi"]
    assert _declaration_line(commented) == "flowchart LR"
    assert _declaration_line(directive) == "sequenceDiagram"
    assert MERMAID_DECLARATION.match(_declaration_line(commented))
    assert MERMAID_DECLARATION.match(_declaration_line(directive))
    assert _reads_as_mermaid(commented)
    assert _reads_as_mermaid(directive)


def _workflow_trigger_paths(text: str, event: str) -> list[str]:
    """Return the `paths:` entries under one `on:` event, without a YAML parser.

    PyYAML is not in `requirements-opencode-review-ci-hashes.txt` and nothing else
    in this repository imports it, so depending on it here would fail collection on
    a clean CI interpreter — and adding it to the hash-locked input would push a new
    dependency into every consumer repository's review sandbox for one assertion.
    The scan is indentation-based over the fixed shape this workflow file has.
    """
    lines = text.split("\n")
    try:
        event_at = next(
            index
            for index, line in enumerate(lines)
            if line.startswith(f"  {event}:")
        )
    except StopIteration:
        return []
    paths_at = next(
        (
            index
            for index in range(event_at + 1, len(lines))
            if lines[index].strip() == "paths:"
            # stop at the next event key at the same indentation as `event`
            and not any(
                lines[between].startswith("  ") and not lines[between].startswith("   ")
                and lines[between].strip().endswith(":")
                for between in range(event_at + 1, index)
            )
        ),
        None,
    )
    if paths_at is None:
        return []
    entries: list[str] = []
    for line in lines[paths_at + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        entries.append(stripped[2:].strip().strip('"').strip("'"))
    return entries


def test_a_markdown_only_change_runs_this_contract() -> None:
    """Markdown changes must trigger a workflow that executes this file.

    Without this the contract is dead on the change it was written for: every
    other suite-running workflow here is path-filtered to Python, Rust, R or its
    own scripts, and `opencode-review-dispatch.yml` runs the Python suite only
    under `has_changed_tracked_files '*.py'`. The commit introducing this file
    masked that gap by adding a `.py` file; a later docs-only corruption would
    not have been caught. Asserted on both event triggers, and on the run step,
    so a path filter that survives while the step stops invoking the suite fails.
    """
    workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    for event in ("pull_request", "push"):
        assert MARKDOWN_GLOB in _workflow_trigger_paths(workflow, event), event
    assert f"pytest -q {Path('tests') / Path(__file__).name}" in workflow


def test_a_keyword_prefix_is_not_a_diagram_declaration() -> None:
    """`startswith` accepts prefixes, so the declaration needs a real boundary.

    `"graphical nonsense".startswith("graph")` is True, and an orphaned node line
    such as `graphNode["orphan"] --> B` starts with `graph` too. Neither renders,
    yet outside the separately pinned `ARCHITECTURE.md` both satisfied the
    repository-wide declaration contract.

    The boundary is the whole claim: this contract asserts a block *declares a
    diagram type*, not that the diagram body is well formed. `pie chart data`
    stays acceptable here because `pie` is the declaration and a boundary follows
    it — whether the remaining pie syntax is valid is mermaid's business, not a
    fence-integrity gate's, and pretending otherwise would make this test fail on
    diagrams that render.
    """
    for impostor in ("graphical nonsense", 'graphNode["orphan"] --> B', "flowcharts"):
        assert not MERMAID_DECLARATION.match(impostor), impostor
    for real in ("graph TD", "flowchart LR", "pie", "erDiagram", "stateDiagram-v2"):
        assert MERMAID_DECLARATION.match(real), real


def test_tilde_fences_are_parsed_and_must_match_their_delimiter(tmp_path: Path) -> None:
    """CommonMark tilde fences count, and a backtick fence does not close one.

    A parser that saw only backticks returned no blocks at all for a tilde
    document, so an unclosed `~~~mermaid` block — or a split involving tilde
    fences — passed the closure, seam and orphan contracts silently.
    """
    closed = "~~~mermaid\ngraph TD\n  A --> B\n~~~\n"
    blocks = _parse_blocks(closed)
    assert len(blocks) == 1
    assert blocks[0][1] == "mermaid"
    assert blocks[0][3] == 4

    unclosed = "~~~mermaid\ngraph TD\n  A --> B\n"
    assert _unclosed_blocks(tmp_path / "tilde.md", unclosed) != []

    # A backtick fence is content inside a tilde block, not its closer.
    mismatched = "~~~mermaid\ngraph TD\n```\n"
    mismatched_blocks = _parse_blocks(mismatched)
    assert len(mismatched_blocks) == 1
    assert mismatched_blocks[0][3] is None
