"""Binary review documents diff as hashed objects, never as "no change"."""

from __future__ import annotations

import base64
import io
import zipfile

import pytest

from scripts.ci import document_blob_diff as dbd
from scripts.ci import noema_review_gate as gate

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
LINK_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def _zip(members: dict[str, bytes | str], *, encrypt: str = "") -> bytes:
    """Build an in-memory ZIP package; ``encrypt`` flags one member as encrypted."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in members.items():
            package.writestr(name, data)
    raw = bytearray(buffer.getvalue())
    if encrypt:
        # zipfile clears the encryption bit on write; set it in the central
        # directory, which is what the reader's infolist() reports.
        start = raw.index(b"PK\x01\x02")
        raw[start + 8] |= 0x1
    return bytes(raw)


def _docx(paragraphs: list[str], *, table: list[list[str]] | None = None, image: bytes | None = None,
          rels: str | None = None, extra: dict[str, bytes | str] | None = None, body: bool = True) -> bytes:
    """Build a synthetic DOCX with paragraphs, an optional table and figure."""
    parts = [f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs]
    if table is not None:
        rows = "".join(
            "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>"
            for row in table
        )
        parts.append(f"<w:tbl>{rows}</w:tbl>")
    if image is not None:
        parts.append('<w:p><w:r><w:drawing><a:blip r:embed="rId9"/></w:drawing></w:r></w:p>')
    inner = f"<w:body>{''.join(parts)}<w:sectPr/></w:body>" if body else ""
    members: dict[str, bytes | str] = {
        "[Content_Types].xml": "<Types/>",
        "word/document.xml": f"<w:document {W} {A} {R}>{inner}</w:document>",
    }
    if rels is None and image is not None:
        rels = f'<Relationships><Relationship Id="rId9" Type="{IMAGE_REL}" Target="media/image1.png"/></Relationships>'
    if rels is not None:
        members["word/_rels/document.xml.rels"] = rels
    if image is not None:
        members["word/media/image1.png"] = image
    members.update(extra or {})
    return _zip(members)


HP = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'


def _hwpx(sections: list[str], *, manifest: str | None = None, extra: dict[str, bytes | str] | None = None) -> bytes:
    """Build a synthetic HWPX with the given section bodies."""
    members: dict[str, bytes | str] = {
        "Contents/content.hpf": manifest
        if manifest is not None
        else '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
        '<opf:item id="img1" href="BinData/image1.png"/></opf:manifest></opf:package>',
        "BinData/image1.png": b"\x89PNG-one",
    }
    for index, body in enumerate(sections):
        members[f"Contents/section{index}.xml"] = f"<hs:sec xmlns:hs=\"urn:hs\" {HP}>{body}</hs:sec>"
    members.update(extra or {})
    return _zip(members)


def _hp(text: str) -> str:
    """One HWPX paragraph."""
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


# ---------------------------------------------------------------- extraction


def test_docx_objects_are_ordered_hashed_and_resolve_figures() -> None:
    """Paragraphs, tables and figures come back in body order with sha256."""
    raw = _docx(["Intro", "Method"], table=[["N", "1020"], ["M", "3.1"]], image=b"PNG1")
    objects = dbd.extract_objects("paper.DOCX", raw)
    assert [(o.kind, o.locator) for o in objects] == [
        ("paragraph", "p1"),
        ("paragraph", "p2"),
        ("table", "tbl1"),
        ("figure", "p3/fig:word/media/image1.png"),
    ]
    assert objects[2].text == "N | 1020\nM | 3.1"
    assert objects[3].text is None and len(objects[3].sha256) == 64


def test_docx_package_absolute_relationship_target_and_hyperlinks_are_allowed() -> None:
    """``/word/media`` targets resolve and external hyperlinks are plain metadata."""
    rels = (
        f'<Relationships><Relationship Id="rId9" Type="{IMAGE_REL}" Target="/word/media/image1.png"/>'
        f'<Relationship Id="rId2" Type="{LINK_REL}" Target="https://example.org" TargetMode="External"/>'
        "</Relationships>"
    )
    objects = dbd.extract_objects("a.docx", _docx([], image=b"PNG", rels=rels))
    assert objects[-1].locator == "p1/fig:word/media/image1.png"


def test_hwpx_objects_split_tables_from_paragraph_text_across_sections() -> None:
    """Section order is numeric; a nested table is its own object."""
    table = "<hp:tbl><hp:tr><hp:tc><hp:t>a</hp:t></hp:tc><hp:tc><hp:t>b</hp:t></hp:tc></hp:tr></hp:tbl>"
    raw = _hwpx(
        [
            _hp("first") + f"<hp:p><hp:run><hp:t>lead</hp:t>{table}</hp:run></hp:p>",
            '<hp:p><hp:pic binaryItemIDRef="img1"/></hp:p><other/>',
        ]
        + [""] * 9
        + [_hp("eleventh")]
    )
    objects = dbd.extract_objects("x.hwpx", raw)
    assert [(o.kind, o.locator, o.text) for o in objects] == [
        ("paragraph", "p1", "first"),
        ("paragraph", "p2", "lead"),
        ("table", "tbl1", "a | b"),
        ("figure", "p3/fig:BinData/image1.png", None),
        ("paragraph", "p4", "eleventh"),
    ]


def test_opaque_documents_are_one_hashed_blob_object() -> None:
    """PDF and images are never decoded; they are one hashed object."""
    (obj,) = dbd.extract_objects("scan.pdf", b"%PDF-1.7 binary")
    assert (obj.kind, obj.locator, obj.text) == ("page", "blob", None)
    assert dbd.is_review_document("fig.PNG") and not dbd.is_review_document("notes.md")


@pytest.mark.parametrize(
    ("path", "raw", "message"),
    (
        ("a.docx", b"not a zip", "not a readable ZIP"),
        ("a.docx", _zip({"../evil": "x"}), "member path is unsafe"),
        ("a.docx", _zip({"word\\evil": "x"}), "member path is unsafe"),
        ("a.docx", _zip({"/abs": "x"}), "member path is unsafe"),
        ("a.docx", _zip({"word/vbaProject.bin": "x"}), "macro content"),
        ("a.hwpx", _zip({"Scripts/main.js": "x"}), "macro content"),
        ("a.docx", _zip({"word/document.xml": "x"}, encrypt="word/document.xml"), "encrypted"),
        ("a.docx", _zip({"big": b"\0" * (2 * 1024 * 1024)}), "compression ratio"),
        ("a.docx", _zip({"[Content_Types].xml": "application/vnd.ms-word.document.macroEnabled"}), "macro-enabled"),
        ("a.docx", _zip({"[Content_Types].xml": "<Types/>"}), "no word/document.xml"),
        ("a.docx", _docx(["x"], body=False), "no body"),
        ("a.docx", _zip({"word/document.xml": "<!DOCTYPE x><x/>"}), "DTD or entity"),
        ("a.docx", _zip({"word/document.xml": "<unclosed>"}), "not well-formed"),
        (
            "a.docx",
            _docx([], rels=f'<Relationships><Relationship Id="r" Type="{IMAGE_REL}" Target="http://x/i.png" TargetMode="External"/></Relationships>'),
            "external image relationship",
        ),
        ("a.docx", _docx([], image=b"P", rels="<Relationships/>"), "relationship is unresolved"),
        (
            "a.docx",
            _docx([], image=b"P", rels=f'<Relationships><Relationship Id="rId9" Type="{IMAGE_REL}" Target="media/gone.png"/></Relationships>'),
            "figure target is missing",
        ),
        ("a.hwpx", _zip({"x": "y"}), "no Contents/content.hpf"),
        ("a.hwpx", _hwpx([], manifest='<m><item id="i" href="https://x/y.png"/></m>'), "external content"),
        ("a.hwpx", _hwpx([]), "no Contents/section"),
        ("a.hwpx", _hwpx(['<hp:p><hp:pic binaryItemIDRef="nope"/></hp:p>']), "reference is unresolved"),
        ("a.txt", b"x", "unsupported review document type"),
        ("noext", b"x", "unsupported review document type"),
    ),
)
def test_unsafe_or_malformed_documents_fail_closed(path: str, raw: bytes, message: str) -> None:
    """Every unsafe or unreadable package raises instead of being skipped."""
    with pytest.raises(dbd.DocumentSafetyError, match=message):
        dbd.extract_objects(path, raw)


def test_size_member_and_expansion_bounds_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blob size, member count and total expansion are bounded."""
    monkeypatch.setattr(dbd, "MAX_BLOB_BYTES", 10)
    with pytest.raises(dbd.DocumentSafetyError, match="blob exceeds"):
        dbd.extract_objects("a.docx", _docx(["x"]))
    with pytest.raises(dbd.DocumentSafetyError, match="blob exceeds"):
        dbd.extract_objects("a.pdf", b"%PDF-" + b"x" * 20)
    monkeypatch.setattr(dbd, "MAX_BLOB_BYTES", 10**9)
    monkeypatch.setattr(dbd, "MAX_MEMBERS", 1)
    with pytest.raises(dbd.DocumentSafetyError, match="more than 1 members"):
        dbd.extract_objects("a.docx", _docx(["x"]))
    monkeypatch.setattr(dbd, "MAX_MEMBERS", 1000)
    monkeypatch.setattr(dbd, "MAX_UNCOMPRESSED_BYTES", 10)
    with pytest.raises(dbd.DocumentSafetyError, match="expands beyond"):
        dbd.extract_objects("a.docx", _docx(["x"]))


# ---------------------------------------------------------------- diff


def _o(kind: str, key: str) -> dbd.DocumentObject:
    """A tiny object whose hash is its key."""
    return dbd.DocumentObject(kind, key, key * 4, key)


def test_diff_objects_reports_changes_with_unchanged_neighbours() -> None:
    """Alignment pairs same-kind replacements, splits kind changes, keeps context."""
    base = [_o("paragraph", "a"), _o("paragraph", "k"), _o("paragraph", "b"), _o("table", "t"), _o("paragraph", "z")]
    head = [_o("paragraph", "a"), _o("paragraph", "k"), _o("paragraph", "B"), _o("figure", "f"), _o("paragraph", "y"), _o("paragraph", "n")]
    changes = [(c, bo, ho) for c, bo, _o1, ho, _o2 in dbd.diff_objects(base, head)]
    assert changes == [
        ("unchanged", 2, 2),
        ("modified", 3, 3),
        ("removed", 4, None),
        ("added", None, 4),
        ("modified", 5, 5),
        ("added", None, 6),
    ]
    middle = [_o("paragraph", "x"), _o("paragraph", "m1"), _o("paragraph", "m2"), _o("paragraph", "m3"), _o("paragraph", "y")]
    edited = [_o("paragraph", "X"), *middle[1:4], _o("paragraph", "Y")]
    assert [(c, bo) for c, bo, *_ in dbd.diff_objects(middle, edited)] == [
        ("modified", 1), ("unchanged", 2), ("unchanged", 4), ("modified", 5),
    ]
    assert [c[0] for c in dbd.diff_objects(base, base[:2])] == ["unchanged", "removed", "removed", "removed"]


# ---------------------------------------------------------------- envelope


def test_envelope_matches_the_co_contract_and_hunks_are_citable() -> None:
    """Envelope fields follow document_diff_review.v1; hunks cite object ordinals."""
    base = _docx(["Intro", "N = 957"], image=b"PNG-A")
    head = _docx(["Intro", "N = 1,020"], image=b"PNG-B")
    review = dbd.build_envelope("o/r", "paper.docx", "1" * 40, "2" * 40, base, head)
    env = review.envelope
    assert set(env) == {
        "contract_version", "repo", "path", "base_blob", "head_blob",
        "extractor_version", "participant_material", "objects",
    }
    assert env["contract_version"] == "document_diff_review.v1" and env["participant_material"] is False
    assert [(o["object_kind"], o["change"], o["base_text"], o["head_text"]) for o in env["objects"]] == [
        ("paragraph", "unchanged", "Intro", "Intro"),
        ("paragraph", "modified", "N = 957", "N = 1,020"),
        ("figure", "modified", None, None),
    ]
    for obj in env["objects"]:
        assert set(obj) == {"page", "object_kind", "locator", "change", "object_hash_base", "object_hash_head", "base_text", "head_text"}
        assert obj["object_hash_base"].startswith("sha256:") and len(obj["object_hash_head"]) == 71
    assert env["objects"][0]["object_hash_base"] == env["objects"][0]["object_hash_head"]
    hunks = dbd.synthetic_hunks(review)
    assert gate.changed_diff_locations(hunks) == {
        ("paper.docx", 2, "LEFT"), ("paper.docx", 2, "RIGHT"),
        ("paper.docx", 3, "LEFT"), ("paper.docx", 3, "RIGHT"),
    }
    assert "(no text extracted; hash only)" in hunks
    assert "PNG-A" not in hunks and "PNG-B" not in hunks and "Intro" not in hunks


def test_added_removed_and_style_only_changes_are_never_no_change() -> None:
    """Added/removed documents and metadata-only edits still yield objects."""
    added = dbd.build_envelope("o/r", "n.pdf", None, "2" * 40, None, b"%PDF-new")
    assert added.envelope["objects"][0]["object_kind"] == "page"
    assert dbd.synthetic_hunks(added).splitlines()[1:3] == ["--- /dev/null", "+++ b/n.pdf"]
    removed = dbd.build_envelope("o/r", "n.pdf", "1" * 40, None, b"%PDF-old", None)
    hunks = dbd.synthetic_hunks(removed, "old/n.pdf")
    assert hunks.splitlines()[:3] == ["diff --git a/old/n.pdf b/n.pdf", "--- a/old/n.pdf", "+++ /dev/null"]
    style = dbd.build_envelope(
        "o/r", "s.docx", "1" * 40, "2" * 40, _docx(["same"]), _docx(["same"], extra={"word/styles.xml": "<s/>"})
    )
    assert [(o["object_kind"], o["locator"], o["change"]) for o in style.envelope["objects"]] == [("style", "package", "modified")]


def test_envelope_rejects_identical_or_missing_blobs_participant_material_secrets_and_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Participant material or secrets are rejected, not redacted, and bounds hold."""
    with pytest.raises(dbd.DocumentSafetyError, match="identical"):
        dbd.build_envelope("o/r", "a.pdf", "1" * 40, "1" * 40, b"x", b"y")
    with pytest.raises(dbd.DocumentSafetyError, match="both base and head blobs are missing"):
        dbd.build_envelope("o/r", "a.pdf", None, None, None, None)
    with pytest.raises(dbd.DocumentSafetyError, match="participant-material directory"):
        dbd.build_envelope("o/r", "study/Interviews/s1.docx", "1" * 40, "2" * 40, _docx(["a"]), _docx(["b"]))
    for text in ("contact kim@example.org", "RRN 900101-1234567", "call 010-1234-5678"):
        with pytest.raises(dbd.DocumentSafetyError, match="participant or secret"):
            dbd.build_envelope("o/r", "a.docx", "1" * 40, "2" * 40, _docx(["ok"]), _docx([text]))
    with pytest.raises(dbd.DocumentSafetyError, match="participant or secret"):
        dbd.build_envelope("o/r", "a.docx", "1" * 40, "2" * 40, _docx(["ok"]), _docx(["token"]), sensitive=lambda t: "token" in t)
    monkeypatch.setattr(dbd, "MAX_OBJECTS", 0)
    with pytest.raises(dbd.DocumentSafetyError, match="more than 0 changed objects"):
        dbd.build_envelope("o/r", "a.docx", "1" * 40, "2" * 40, _docx(["a"]), _docx(["b"]))


# ---------------------------------------------------------------- stanzas


BINARY_ONLY_DIFF = (
    "diff --git a/paper.docx b/paper.docx\n"
    "index 1111111..2222222 100644\n"
    "Binary files a/paper.docx and b/paper.docx differ\n"
    "diff --git a/logo.bin b/logo.bin\n"
    "Binary files a/logo.bin and b/logo.bin differ\n"
    "diff --git a/new.pdf b/new.pdf\n"
    "new file mode 100644\n"
    "Binary files /dev/null and b/new.pdf differ\n"
)


def test_binary_stanzas_are_found_and_replaced_per_document() -> None:
    """Only review-document binaries are selected; others keep their stanza."""
    assert dbd.binary_document_stanzas(BINARY_ONLY_DIFF + BINARY_ONLY_DIFF) == [
        ("paper.docx", "paper.docx"),
        (None, "new.pdf"),
    ]
    replaced = dbd.replace_binary_stanzas(BINARY_ONLY_DIFF, {("paper.docx", "paper.docx"): "HUNK"})
    assert replaced.startswith("HUNK\ndiff --git a/logo.bin")
    assert "Binary files /dev/null and b/new.pdf differ" in replaced


# ---------------------------------------------------------------- gate


def test_binary_only_textual_diff_alone_has_no_citable_line() -> None:
    """RED characterization: the raw binary-only diff cannot carry a formal verdict."""
    verdict = {"decision": "approve", "reviewed_lines": [], "findings": []}
    with pytest.raises(RuntimeError, match="requires parseable changed-line evidence"):
        gate.validate_substantive_verdict(verdict, BINARY_ONLY_DIFF)


def _fake_github(monkeypatch: pytest.MonkeyPatch, blobs: dict[tuple[str, str], bytes]) -> None:
    """Serve contents/blobs/compare calls from ``blobs`` keyed by (path, ref)."""
    shas = {key: f"{index:040x}" for index, key in enumerate(blobs, start=1)}

    def fake_run(args, *, stdin=None):
        """Return canned GitHub API output for the materialization calls."""
        url = args[2]
        if "/compare/" in url:
            return "b" * 40
        if "/contents/" in url:
            path, ref = url.split("/contents/", 1)[1].split("?ref=")
            return shas[(path, ref)]
        sha = url.rsplit("/", 1)[1]
        key = next(k for k, v in shas.items() if v == sha)
        return base64.b64encode(blobs[key]).decode()

    monkeypatch.setattr(gate, "run", fake_run)


def test_binary_only_docx_pr_yields_a_citable_request_changes_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """GREEN: a binary-only PR produces object hunks that a real finding can cite."""
    head = "c" * 40
    _fake_github(
        monkeypatch,
        {
            ("paper.docx", "b" * 40): _docx(["Intro", "N = 957"]),
            ("paper.docx", head): _docx(["Intro", "N = 1,020"]),
            ("new.pdf", head): b"%PDF-1.7",
        },
    )
    pr = {"baseRefOid": "a" * 40, "headRefOid": head}
    diff, truncated = gate.augment_binary_document_diff("o/r", pr, BINARY_ONLY_DIFF, False)
    assert not truncated
    assert "Binary files a/paper.docx" not in diff and "Binary files a/logo.bin" in diff
    verdict = {
        "decision": "request_changes",
        "reviewed_lines": [{"path": "paper.docx", "line": 2, "side": "RIGHT"}],
        "findings": [{"path": "paper.docx", "line": 2, "side": "RIGHT", "message": "Sample size contradicts Table 1."}],
    }
    locations = gate.changed_diff_locations(diff)
    assert ("paper.docx", 2, "RIGHT") in locations and ("new.pdf", 1, "RIGHT") in locations
    for finding in verdict["findings"]:
        assert (finding["path"], finding["line"], finding["side"]) in locations


def test_augmentation_passes_through_text_diffs_and_fails_closed_on_unsafe_blobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """No stanza means no API call; a safety rejection fails the review closed."""
    monkeypatch.setattr(gate, "run", lambda *_a, **_k: pytest.fail("no API call expected"))
    assert gate.augment_binary_document_diff("o/r", {}, "diff --git a/x b/x\n", True) == ("diff --git a/x b/x\n", True)
    head = "c" * 40
    _fake_github(
        monkeypatch,
        {("paper.docx", "b" * 40): _docx(["ok"]), ("paper.docx", head): _zip({"word/vbaProject.bin": "x"}), ("new.pdf", head): b"%PDF"},
    )
    with pytest.raises(RuntimeError, match="binary document review failed closed for paper.docx: package contains macro"):
        gate.augment_binary_document_diff("o/r", {"baseRefOid": "a" * 40, "headRefOid": head}, BINARY_ONLY_DIFF, False)


def test_blob_fetch_fails_closed_on_missing_sha_or_bad_base64(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing blob SHA or malformed payload raises."""
    monkeypatch.setattr(gate, "run", lambda args, **_k: "" if "/contents/" in args[2] else "!")
    with pytest.raises(RuntimeError, match="did not return a blob SHA"):
        gate.fetch_file_blob_at_ref("o/r", "a b.pdf", "main")
    monkeypatch.setattr(gate, "run", lambda args, **_k: "c" * 40 if "/contents/" in args[2] else "!!notbase64")
    with pytest.raises(RuntimeError, match="malformed base64"):
        gate.fetch_file_blob_at_ref("o/r", "a.pdf", "main")


def test_opaque_head_content_is_never_decoded_into_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """PDF/image bytes no longer reach the changed-file context as mojibake."""
    monkeypatch.setattr(gate, "run", lambda *_a, **_k: base64.b64encode(b"%PDF secret-bytes").decode())
    text = gate.fetch_file_content_at_ref("o/r", "scan.pdf", "h" * 40)
    assert "secret-bytes" not in text and "object-level diff" in text


# ---------------------------------------------------------------- CO byte bounds and full-body privacy


def _texts(envelope: dict) -> list[str]:
    """All non-null base/head texts in an envelope."""
    return [t for o in envelope["objects"] for t in (o["base_text"], o["head_text"]) if t is not None]


def test_korean_object_text_is_cut_on_utf8_bytes_not_characters() -> None:
    """A 5,000-character Korean paragraph (15,000 UTF-8 bytes) fits the 8 KiB byte bound.

    RED on bddeb901: text was cut at 8,192 characters, so the envelope kept all
    15,000 bytes and contextual-orchestrator#1220 answered 400 invalid_text.
    """
    long_ko = "가" * 5000
    review = dbd.build_envelope("o/r", "k.docx", "1" * 40, "2" * 40, _docx(["짧음"]), _docx([long_ko]))
    head_text = review.envelope["objects"][0]["head_text"]
    assert len(head_text.encode("utf-8")) <= dbd.MAX_OBJECT_TEXT_BYTES == 8 * 1024
    assert head_text == "가" * (8 * 1024 // 3)


def test_envelope_total_stays_within_256_kib_utf8_bytes() -> None:
    """Forty ~8.1 KB Korean paragraphs exceed 256 KiB in bytes, not in characters.

    RED on bddeb901: the total counted characters, so the envelope carried more
    than 256 KiB and contextual-orchestrator#1220 answered 413 request_too_large.
    """
    base = _docx([f"{i}" + "나" * 2700 for i in range(40)])
    head = _docx([f"{i}" + "다" * 2700 for i in range(40)])
    review = dbd.build_envelope("o/r", "k.docx", "1" * 40, "2" * 40, base, head)
    total = sum(len(t.encode("utf-8")) for t in _texts(review.envelope))
    assert total <= dbd.MAX_ENVELOPE_TEXT_BYTES
    assert len(review.envelope["objects"]) == 40
    assert all(o["change"] == "modified" for o in review.envelope["objects"])


def test_unchanged_context_is_dropped_before_changed_objects_lose_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changed objects claim the budget first; context goes when bytes or slots run out."""
    base = _docx(["ctx-a", "old", "ctx-b"])
    head = _docx(["ctx-a", "new", "ctx-b"])
    monkeypatch.setattr(dbd, "MAX_ENVELOPE_TEXT_BYTES", 6)
    review = dbd.build_envelope("o/r", "c.docx", "1" * 40, "2" * 40, base, head)
    assert [(o["change"], o["base_text"], o["head_text"]) for o in review.envelope["objects"]] == [
        ("modified", "old", "new"),
    ]
    monkeypatch.setattr(dbd, "MAX_ENVELOPE_TEXT_BYTES", 1024)
    monkeypatch.setattr(dbd, "MAX_OBJECTS", 2)
    review = dbd.build_envelope("o/r", "c.docx", "1" * 40, "2" * 40, base, head)
    assert [o["change"] for o in review.envelope["objects"]] == ["unchanged", "modified"]


def test_control_characters_are_blanked_to_match_the_co_text_rule() -> None:
    """contextual-orchestrator rejects control characters other than newline and tab.

    XML 1.0 already refuses most of them; a ``&#13;`` reference still yields a
    carriage return, which is blanked instead of sent.
    """
    review = dbd.build_envelope(
        "o/r", "c.docx", "1" * 40, "2" * 40, _docx(["a"]), _docx(["x&#13;y\tz"])
    )
    assert review.envelope["objects"][0]["head_text"] == "x y\tz"


def test_participant_identifier_far_from_the_change_fails_the_review_closed() -> None:
    """A phone number in an unchanged paragraph far from the edit is still rejected.

    RED on bddeb901: only diffed objects and their neighbours were scanned, so
    the phone number was not in the envelope and passed, while the full body
    still reached the changed-file context.
    """
    body = ["title", "010-2345-6789 연락처", "filler 1", "filler 2", "filler 3", "result old"]
    edited = body[:-1] + ["result new"]
    with pytest.raises(dbd.DocumentSafetyError, match="participant or secret pattern in extracted text at p2"):
        dbd.build_envelope("o/r", "far.docx", "1" * 40, "2" * 40, _docx(body), _docx(edited))


def test_full_document_context_is_withheld_when_it_carries_participant_material(monkeypatch: pytest.MonkeyPatch) -> None:
    """The changed-file context path applies the same gate to the whole extracted body."""
    raw = _docx(["intro", "call 010-2345-6789"])
    monkeypatch.setattr(gate, "run", lambda *_a, **_k: base64.b64encode(raw).decode())
    monkeypatch.setattr(gate, "extract_review_document", lambda _path, _raw: "intro\ncall 010-2345-6789")
    with pytest.raises(RuntimeError, match="document context withheld: participant or secret pattern"):
        gate.fetch_file_content_at_ref("o/r", "far.docx", "c" * 40)
    monkeypatch.setattr(gate, "extract_review_document", lambda _path, _raw: "intro only")
    assert gate.fetch_file_content_at_ref("o/r", "ok.docx", "c" * 40) == "intro only"
