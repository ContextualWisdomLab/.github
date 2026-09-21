"""Object-level base/head diff for binary review documents, fail closed.

GitHub renders a changed DOCX/HWPX/PDF/image as ``Binary files … differ`` with
no hunk. An empty textual patch is not "no change"; it is an unsupported
textual diff. This module turns the base and head blobs into ordered document
objects (paragraphs, tables, figures, or one opaque blob), diffs them, and
emits the ``document_diff_review.v1`` envelope. Only bounded extracted text and
sha256 hashes leave the runner. Original bytes, embedded media, macros,
external relationships, and participant or secret patterns never do: they
raise :class:`DocumentSafetyError` instead.
"""

from __future__ import annotations

import difflib
import hashlib
import io
import re
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

EXTRACTOR_VERSION = "document_blob_diff/1"
CONTRACT_VERSION = "document_diff_review.v1"
PACKAGE_SUFFIXES = frozenset({".docx", ".hwpx"})
OPAQUE_SUFFIXES = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
)
REVIEW_DOCUMENT_SUFFIXES = PACKAGE_SUFFIXES | OPAQUE_SUFFIXES
MAX_BLOB_BYTES = 25 * 1024 * 1024
MAX_MEMBERS = 1000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_MEMBER_RATIO = 200
RATIO_FLOOR_BYTES = 1024 * 1024
MAX_OBJECTS = 200
# UTF-8 byte bounds, matching contextual-orchestrator document_diff_review.v1.
MAX_OBJECT_TEXT_BYTES = 8 * 1024
MAX_ENVELOPE_TEXT_BYTES = 256 * 1024
_DISALLOWED_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\ud800-\udfff]")
# Relationship types that make a reader fetch or execute remote content. A
# plain hyperlink is metadata and stays allowed.
_REMOTE_CONTENT_REL = re.compile(r"/(image|oleObject|attachedTemplate|frame|subDocument|package)$")
_PARTICIPANT_DIRECTORY = re.compile(
    r"(^|/)(participants|participant_data|raw_data|subjects|interviews|consent|consents|pii)(/|$)",
    re.IGNORECASE,
)
_PARTICIPANT_PATTERNS = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)"),
    re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"),
)


class DocumentSafetyError(RuntimeError):
    """A blob cannot be reviewed without sending unsafe or unbounded content."""


@dataclass(frozen=True)
class DocumentObject:
    """One ordered, hashed document object; ``text`` is None for figures/blobs."""

    kind: str
    locator: str
    sha256: str
    text: str | None


def is_review_document(path: str) -> bool:
    """Return whether ``path`` is a binary document this module reviews."""
    return PurePosixPath(path).suffix.lower() in REVIEW_DOCUMENT_SUFFIXES


def _sha256(data: bytes) -> str:
    """Return the lowercase hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def _local(tag: str) -> str:
    """Return an XML tag without its namespace."""
    return tag.rsplit("}", 1)[-1]


def open_package(raw: bytes) -> zipfile.ZipFile:
    """Open a DOCX/HWPX container after size, bomb, traversal and macro checks."""
    if len(raw) > MAX_BLOB_BYTES:
        raise DocumentSafetyError(f"blob exceeds {MAX_BLOB_BYTES} bytes")
    try:
        package = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise DocumentSafetyError("document is not a readable ZIP package") from exc
    members = package.infolist()
    if len(members) > MAX_MEMBERS:
        raise DocumentSafetyError(f"package has more than {MAX_MEMBERS} members")
    total = 0
    for member in members:
        name = member.filename
        if name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name:
            raise DocumentSafetyError(f"package member path is unsafe: {name!r}")
        if member.flag_bits & 0x1:
            raise DocumentSafetyError("package member is encrypted")
        lowered = name.lower()
        if lowered.endswith("vbaproject.bin") or lowered.startswith("scripts/"):
            raise DocumentSafetyError(f"package contains macro content: {name!r}")
        total += member.file_size
        if (
            member.file_size > RATIO_FLOOR_BYTES
            and member.file_size > MAX_MEMBER_RATIO * max(member.compress_size, 1)
        ):
            raise DocumentSafetyError(f"package member compression ratio is unsafe: {name!r}")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise DocumentSafetyError(f"package expands beyond {MAX_UNCOMPRESSED_BYTES} bytes")
    content_types = _read_optional(package, "[Content_Types].xml")
    if content_types is not None and b"macroEnabled" in content_types:
        raise DocumentSafetyError("package declares macro-enabled content")
    return package


def _read_optional(package: zipfile.ZipFile, name: str) -> bytes | None:
    """Read one member or return None when it is absent."""
    try:
        return package.read(name)
    except KeyError:
        return None


def _parse(data: bytes, name: str) -> ElementTree.Element:
    """Parse package XML, failing closed on malformed or DTD-bearing input."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise DocumentSafetyError(f"{name} declares a DTD or entity")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        raise DocumentSafetyError(f"{name} is not well-formed XML") from exc


def _text(element: ElementTree.Element, text_tag: str, skip: set[int] | None = None) -> str:
    """Join ``text_tag`` descendants, skipping any subtree rooted in ``skip``."""
    parts: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        """Depth-first text collection that honours ``skip``."""
        if skip and id(node) in skip:
            return
        if _local(node.tag) == text_tag and node.text:
            parts.append(node.text)
        for child in node:
            walk(child)

    walk(element)
    return "".join(parts)


def _table_text(table: ElementTree.Element, row_tag: str, cell_tag: str, text_tag: str) -> str:
    """Render a table as ``cell | cell`` rows separated by newlines."""
    rows = []
    for row in table.iter():
        if _local(row.tag) != row_tag:
            continue
        cells = [_text(cell, text_tag) for cell in row if _local(cell.tag) == cell_tag]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _figure(package: zipfile.ZipFile, target: str, locator: str) -> DocumentObject:
    """Hash one embedded media member; a missing target fails closed."""
    data = _read_optional(package, target)
    if data is None:
        raise DocumentSafetyError(f"figure target is missing: {target!r}")
    return DocumentObject("figure", locator, _sha256(data), None)


def _text_object(kind: str, locator: str, text: str) -> DocumentObject:
    """Hash a paragraph/table by its extracted text."""
    return DocumentObject(kind, locator, _sha256(text.encode("utf-8")), text)


def extract_docx(raw: bytes) -> list[DocumentObject]:
    """Return DOCX body paragraphs, tables and figures in document order."""
    package = open_package(raw)
    document = _read_optional(package, "word/document.xml")
    if document is None:
        raise DocumentSafetyError("DOCX has no word/document.xml")
    relationships: dict[str, str] = {}
    rels = _read_optional(package, "word/_rels/document.xml.rels")
    if rels is not None:
        for rel in _parse(rels, "document.xml.rels"):
            if rel.get("TargetMode") == "External" and _REMOTE_CONTENT_REL.search(rel.get("Type", "")):
                raise DocumentSafetyError(f"DOCX has an external {rel.get('Type', '').rsplit('/', 1)[-1]} relationship")
            target = rel.get("Target", "")
            relationships[rel.get("Id", "")] = target[1:] if target.startswith("/") else "word/" + target
    body = next((node for node in _parse(document, "document.xml") if _local(node.tag) == "body"), None)
    if body is None:
        raise DocumentSafetyError("DOCX document has no body")
    objects: list[DocumentObject] = []
    paragraphs = tables = 0
    for node in body:
        kind = _local(node.tag)
        if kind == "tbl":
            tables += 1
            objects.append(_text_object("table", f"tbl{tables}", _table_text(node, "tr", "tc", "t")))
        elif kind == "p":
            paragraphs += 1
            text = _text(node, "t")
            if text:
                objects.append(_text_object("paragraph", f"p{paragraphs}", text))
            for blip in (d for d in node.iter() if _local(d.tag) == "blip"):
                rel_id = next((v for k, v in blip.attrib.items() if _local(k) == "embed"), "")
                if rel_id not in relationships:
                    raise DocumentSafetyError(f"DOCX figure relationship is unresolved: {rel_id!r}")
                objects.append(_figure(package, relationships[rel_id], f"p{paragraphs}/fig:{relationships[rel_id]}"))
    return objects


def extract_hwpx(raw: bytes) -> list[DocumentObject]:
    """Return HWPX section paragraphs, tables and figures in document order."""
    package = open_package(raw)
    manifest = _read_optional(package, "Contents/content.hpf")
    if manifest is None:
        raise DocumentSafetyError("HWPX has no Contents/content.hpf")
    items: dict[str, str] = {}
    spine: list[str] = []
    for item in _parse(manifest, "content.hpf").iter():
        if _local(item.tag) == "item":
            href = item.get("href", "")
            if re.match(r"^[a-z][a-z0-9+.-]*:", href, re.IGNORECASE):
                raise DocumentSafetyError(f"HWPX manifest references external content: {href!r}")
            items[item.get("id", "")] = href
        elif _local(item.tag) == "itemref":
            spine.append(item.get("idref", ""))
    if spine:
        # Reading order is the manifest spine, as the HWPX reader uses it.
        sections = []
        for idref in spine:
            href = items.get(idref, "")
            if not re.fullmatch(r"Contents/section\d+\.xml", href):
                continue
            if href not in package.namelist():
                raise DocumentSafetyError(f"HWPX spine section is missing: {href!r}")
            sections.append(href)
    else:
        sections = sorted(
            (n for n in package.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n).group()),
        )
    if not sections:
        raise DocumentSafetyError("HWPX has no Contents/section*.xml")
    objects: list[DocumentObject] = []
    paragraphs = tables = 0
    for section in sections:
        for node in _parse(package.read(section), section):
            if _local(node.tag) != "p":
                continue
            paragraphs += 1
            nested = [d for d in node.iter() if _local(d.tag) == "tbl"]
            text = _text(node, "t", skip={id(t) for t in nested})
            if text:
                objects.append(_text_object("paragraph", f"p{paragraphs}", text))
            for table in nested:
                tables += 1
                objects.append(_text_object("table", f"tbl{tables}", _table_text(table, "tr", "tc", "t")))
            for pic in (d for d in node.iter() if "binaryItemIDRef" in d.attrib):
                ref = pic.get("binaryItemIDRef", "")
                if ref not in items:
                    raise DocumentSafetyError(f"HWPX figure reference is unresolved: {ref!r}")
                objects.append(_figure(package, items[ref], f"p{paragraphs}/fig:{items[ref]}"))
    return objects


def extract_objects(path: str, raw: bytes) -> list[DocumentObject]:
    """Extract ordered objects; PDF/images are one opaque hashed ``page`` object."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".docx":
        return extract_docx(raw)
    if suffix == ".hwpx":
        return extract_hwpx(raw)
    if suffix in OPAQUE_SUFFIXES:
        if len(raw) > MAX_BLOB_BYTES:
            raise DocumentSafetyError(f"blob exceeds {MAX_BLOB_BYTES} bytes")
        return [DocumentObject("page", "blob", _sha256(raw), None)]
    raise DocumentSafetyError(f"unsupported review document type: {suffix or path!r}")


CORRESPONDING_AUTHOR_MARKER = "[CORRESPONDING_AUTHOR_EMAIL]"
FRONT_MATTER_MAX_PARAGRAPHS = 20
_EMAIL = _PARTICIPANT_PATTERNS[0]
_CONTACT_DECLARATION = re.compile(r"corresponding\s+author|correspondence|교신\s*저자", re.IGNORECASE)
_FRONT_MATTER_END = re.compile(r"^\s*(abstract|초록|요약|introduction|서론|1\.\s)", re.IGNORECASE)
_CAPTION = re.compile(r"^\s*(figure|fig\.|그림)\s*\d+", re.IGNORECASE)


def redact_corresponding_author(paragraphs: Sequence[str], allowlist: frozenset[str]) -> list[str]:
    """Replace declared, allowlisted corresponding-author emails with a marker.

    An address is replaced only when it is on the workflow's exact allowlist
    AND sits in a front-matter paragraph (before the abstract/introduction and
    within the first ``FRONT_MATTER_MAX_PARAGRAPHS``) that declares author
    contact. Every other email, including the same address anywhere else,
    is left in place so the participant scan rejects the document.
    """
    out = []
    front = True
    for index, text in enumerate(paragraphs):
        if front and (index >= FRONT_MATTER_MAX_PARAGRAPHS or _FRONT_MATTER_END.match(text)):
            front = False
        emails = _EMAIL.findall(text)
        if (
            emails
            and front
            and _CONTACT_DECLARATION.search(text)
            and all(email.lower() in allowlist for email in emails)
        ):
            text = _EMAIL.sub(CORRESPONDING_AUTHOR_MARKER, text)
        out.append(text)
    return out


def _apply_contact_policy(objects: Sequence[DocumentObject], allowlist: frozenset[str]) -> list[DocumentObject]:
    """Apply :func:`redact_corresponding_author` to paragraph objects, rehashing them."""
    paragraphs = [o for o in objects if o.kind == "paragraph"]
    redacted = iter(redact_corresponding_author([o.text or "" for o in paragraphs], allowlist))
    out = []
    for obj in objects:
        if obj.kind == "paragraph":
            text = next(redacted)
            obj = obj if text == obj.text else _text_object("paragraph", obj.locator, text)
        out.append(obj)
    return out


def _attach_captions(objects: Sequence[DocumentObject]) -> list[DocumentObject]:
    """Give each figure the text of an adjacent "Figure N"/"그림 N" caption paragraph.

    The figure keeps its media hash, so a changed image with an unchanged
    caption is visible as a modified figure whose base and head text agree.
    """
    out = list(objects)
    for index, obj in enumerate(out):
        if obj.kind != "figure":
            continue
        for near in (index + 1, index - 1):
            if 0 <= near < len(out) and out[near].kind == "paragraph" and _CAPTION.match(out[near].text or ""):
                out[index] = DocumentObject("figure", obj.locator, obj.sha256, out[near].text)
                break
    return out


def diff_objects(
    base: Sequence[DocumentObject], head: Sequence[DocumentObject]
) -> list[tuple[str, int | None, DocumentObject | None, int | None, DocumentObject | None]]:
    """Align base/head objects by (kind, hash) and return changes with context.

    Each entry is ``(change, base_ordinal, base_object, head_ordinal,
    head_object)`` with 1-based ordinals; ``change`` is added, removed,
    modified, or unchanged. Only the unchanged object on each side of a change
    is kept, as body/table/caption consistency context.
    """
    keys_a = [(o.kind, o.sha256) for o in base]
    keys_b = [(o.kind, o.sha256) for o in head]
    opcodes = difflib.SequenceMatcher(a=keys_a, b=keys_b, autojunk=False).get_opcodes()
    changes = []
    for position, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            keep = set()
            if position > 0:
                keep.add(0)
            if position < len(opcodes) - 1:
                keep.add(i2 - i1 - 1)
            for offset in sorted(keep):
                changes.append(("unchanged", i1 + offset + 1, base[i1 + offset], j1 + offset + 1, head[j1 + offset]))
            continue
        span = max(i2 - i1, j2 - j1)
        for offset in range(span):
            i, j = i1 + offset, j1 + offset
            old = base[i] if i < i2 else None
            new = head[j] if j < j2 else None
            if old is not None and new is not None and old.kind == new.kind:
                changes.append(("modified", i + 1, old, j + 1, new))
                continue
            if old is not None:
                changes.append(("removed", i + 1, old, None, None))
            if new is not None:
                changes.append(("added", None, None, j + 1, new))
    return changes


def assert_no_participant_material(text: str, where: str, sensitive: Callable[[str], bool]) -> None:
    """Reject text carrying participant identifiers or secrets; never redact."""
    if any(p.search(text) for p in _PARTICIPANT_PATTERNS) or sensitive(text):
        raise DocumentSafetyError(f"participant or secret pattern in extracted text at {where}")


TRUNCATION_MARKER = "…[truncated]"


def _bounded(text: str | None) -> str | None:
    """Return ``text`` within ``MAX_OBJECT_TEXT_BYTES`` UTF-8 bytes.

    Controls other than newline and tab are blanked. A cut text ends with
    ``TRUNCATION_MARKER`` so a reviewer can never mistake it for the whole text.
    """
    if text is None:
        return None
    clean = _DISALLOWED_CONTROL.sub(" ", text)
    encoded = clean.encode("utf-8")
    if len(encoded) <= MAX_OBJECT_TEXT_BYTES:
        return clean
    room = MAX_OBJECT_TEXT_BYTES - len(TRUNCATION_MARKER.encode("utf-8"))
    return encoded[:room].decode("utf-8", "ignore") + TRUNCATION_MARKER


def _size(text: str | None) -> int:
    """Return the UTF-8 byte length of optional text."""
    return len(text.encode("utf-8")) if text else 0


@dataclass(frozen=True)
class DocumentReview:
    """A CO-strict envelope plus the object ordinals used for citable hunks."""

    envelope: dict[str, Any]
    ordinals: tuple[tuple[int | None, int | None], ...]


def _hash(digest: str | None) -> str | None:
    """Return the envelope's ``sha256:<hex>`` form of a digest."""
    return f"sha256:{digest}" if digest else None


def build_envelope(
    repo: str,
    path: str,
    base_blob: str | None,
    head_blob: str | None,
    base_raw: bytes | None,
    head_raw: bytes | None,
    sensitive: Callable[[str], bool] = lambda _text: False,
    corresponding_author_emails: frozenset[str] = frozenset(),
) -> DocumentReview:
    """Build a bounded ``document_diff_review.v1`` envelope for one path."""
    if _PARTICIPANT_DIRECTORY.search(path):
        raise DocumentSafetyError(f"path is under a participant-material directory: {path}")
    if base_blob is None and head_blob is None:
        raise DocumentSafetyError("both base and head blobs are missing")
    if base_blob == head_blob:
        raise DocumentSafetyError("base and head blobs are identical")
    base = extract_objects(path, base_raw) if base_raw is not None else []
    head = extract_objects(path, head_raw) if head_raw is not None else []
    base = _attach_captions(_apply_contact_policy(base, corresponding_author_emails))
    head = _attach_captions(_apply_contact_policy(head, corresponding_author_emails))
    # Scan every extracted object, not only the diffed ones: the same document
    # text also reaches the changed-file context, so a participant identifier
    # anywhere in either blob fails the review closed.
    for obj in (*base, *head):
        if obj.text is not None:
            assert_no_participant_material(obj.text, obj.locator, sensitive)
    entries = diff_objects(base, head)
    changed = [e for e in entries if e[0] != "unchanged"]
    context = [e for e in entries if e[0] == "unchanged"]
    if len(changed) > MAX_OBJECTS:
        raise DocumentSafetyError(f"document diff has more than {MAX_OBJECTS} changed objects")
    # Every changed object is sent in full: if any changed text would be cut by
    # the per-object bound or the envelope budget, the review fails closed and
    # no provider is called. Only unchanged context is cut (marked) or dropped.
    budget = MAX_ENVELOPE_TEXT_BYTES
    kept: dict[int, tuple[str | None, str | None]] = {}
    for entry in changed:
        _change, _bo, old, _ho, new = entry
        texts = (_bounded(old.text if old else None), _bounded(new.text if new else None))
        if any(_size(text) > MAX_OBJECT_TEXT_BYTES for text in (old and old.text, new and new.text)):
            raise DocumentSafetyError(
                f"changed object {(new or old).locator} exceeds the {MAX_OBJECT_TEXT_BYTES}-byte text bound"
            )
        budget -= _size(texts[0]) + _size(texts[1])
        kept[id(entry)] = texts
    if budget < 0:
        raise DocumentSafetyError(
            f"changed document objects exceed the {MAX_ENVELOPE_TEXT_BYTES}-byte review budget"
        )
    for entry in context[: MAX_OBJECTS - len(changed)]:
        _change, _bo, old, _ho, new = entry
        texts = (_bounded(old.text if old else None), _bounded(new.text if new else None))
        cost = _size(texts[0]) + _size(texts[1])
        if cost > budget:
            continue
        budget -= cost
        kept[id(entry)] = texts
    objects: list[dict[str, Any]] = []
    ordinals: list[tuple[int | None, int | None]] = []
    for entry in entries:
        if id(entry) not in kept:
            continue
        change, base_ord, old, head_ord, new = entry
        subject = new or old
        base_text, head_text = kept[id(entry)]
        objects.append(
            {
                "page": None,
                "object_kind": subject.kind,
                "locator": subject.locator[:256],
                "change": change,
                "object_hash_base": _hash(old.sha256 if old else None),
                "object_hash_head": _hash(new.sha256 if new else None),
                "base_text": base_text,
                "head_text": head_text,
            }
        )
        ordinals.append((base_ord, head_ord))
    if not changed and base_raw is not None and head_raw is not None:
        # The bytes changed but no body object did (styles, settings, metadata):
        # still a reviewable change, never "no change".
        objects.append(
            {
                "page": None,
                "object_kind": "style",
                "locator": "package",
                "change": "modified",
                "object_hash_base": _hash(_sha256(base_raw)),
                "object_hash_head": _hash(_sha256(head_raw)),
                "base_text": None,
                "head_text": None,
            }
        )
        ordinals.append((1, 1))
    envelope = {
        "contract_version": CONTRACT_VERSION,
        "repo": repo,
        "path": path,
        "base_blob": base_blob,
        "head_blob": head_blob,
        "extractor_version": EXTRACTOR_VERSION,
        "participant_material": False,
        "objects": objects,
    }
    return DocumentReview(envelope, tuple(ordinals))


def _line(obj: dict[str, Any], side: str) -> str:
    """Render one synthetic diff line for an object side."""
    digest = obj[f"object_hash_{side}"].removeprefix("sha256:")[:12]
    text = obj[f"{side}_text"]
    body = " ".join(text.split())[:500] if text is not None else "(no text extracted; hash only)"
    return f"[{obj['object_kind']} {obj['locator']} sha256:{digest}] {body}"


def synthetic_hunks(review: DocumentReview, old_path: str | None = None) -> str:
    """Render changed objects as unified-diff hunks citable as ``path:ordinal``.

    LEFT line numbers are base object ordinals and RIGHT line numbers are head
    object ordinals, so existing changed-line validation accepts citations of
    document objects without any new location type. Unchanged context objects
    stay in the envelope only.
    """
    envelope = review.envelope
    path = envelope["path"]
    old = old_path or path
    lines = [
        f"diff --git a/{old} b/{path}",
        f"--- a/{old}" if envelope["base_blob"] else "--- /dev/null",
        f"+++ b/{path}" if envelope["head_blob"] else "+++ /dev/null",
    ]
    for obj, (left, new) in zip(envelope["objects"], review.ordinals):
        if obj["change"] == "unchanged":
            continue
        lines.append(f"@@ -{left or 0},{1 if left else 0} +{new or 0},{1 if new else 0} @@ {obj['change']}")
        if left:
            lines.append("-" + _line(obj, "base"))
        if new:
            lines.append("+" + _line(obj, "head"))
    return "\n".join(lines)


_BINARY_STANZA = re.compile(r"^Binary files (?:a/(?P<old>.+)|/dev/null) and (?:b/(?P<new>.+)|/dev/null) differ$")


def _stanza(block: str) -> tuple[str | None, str | None] | None:
    """Return the ``(old, new)`` paths of a block's binary stanza, if any."""
    for line in block.splitlines():
        match = _BINARY_STANZA.match(line)
        if match:
            return match.group("old"), match.group("new")
    return None


def binary_document_stanzas(diff: str) -> list[tuple[str | None, str | None]]:
    """Return ``(old, new)`` review-document paths the diff reports only as binary."""
    stanzas = []
    for block in re.split(r"(?m)^(?=diff --git )", diff):
        pair = _stanza(block)
        if pair and is_review_document(pair[1] or pair[0]) and pair not in stanzas:
            stanzas.append(pair)
    return stanzas


def replace_binary_stanzas(diff: str, hunks: dict[tuple[str | None, str | None], str]) -> str:
    """Replace each ``diff --git`` block of a reviewed binary pair with its hunks."""
    out = []
    for block in re.split(r"(?m)^(?=diff --git )", diff):
        pair = _stanza(block)
        out.append(hunks[pair] + "\n" if pair in hunks else block)
    return "".join(out)
