#!/usr/bin/env python3
"""Reviewer-owned progress memory; deliberately not a review-approval authority.

A trusted launcher seeds an exact base/head inventory, including relationship
work. Agents record immutable content-addressed evidence and finding references.
The memory.md view is only a bounded index; it never replaces original source,
independent probe validation, or protected review gates. Do not store secrets,
raw provider reasoning, or source text in this ledger.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from urllib.parse import quote


class MemoryError(ValueError):
    """Review progress is malformed, stale, or outside the trusted scope."""


def _hash(value: object) -> str:
    """Bind a canonical manifest without retaining raw source evidence."""
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sha(value: object, length: int = 64) -> bool:
    """Accept only canonical digest references, never arbitrary file paths."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is not None


def _page_limit(limit: int) -> None:
    """Make the model-facing index size an explicit caller choice."""
    if type(limit) is not int or limit < 1:
        raise MemoryError("invalid_limit")


@dataclass(frozen=True)
class ReviewIdentity:
    """Exact review namespace supplied by the trusted launcher, not PR text."""

    repository: str
    pr_number: int
    base_sha: str
    head_sha: str
    reviewer: str
    policy_revision: str

    def __post_init__(self) -> None:
        """Reject ambiguous source or reviewer identity before state is opened."""
        if (not isinstance(self.repository, str)
                or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository) is None
                or len(self.repository) > 256
                or type(self.pr_number) is not int or self.pr_number < 1
                or not _sha(self.base_sha, 40) or not _sha(self.head_sha, 40)
                or any(not isinstance(v, str) or not v.strip() or len(v) > 256
                       for v in (self.reviewer, self.policy_revision))):
            raise MemoryError("invalid_identity")


@dataclass(frozen=True)
class WorkUnit:
    """One source slice or cross-boundary obligation in a complete inventory."""

    unit_id: str
    kind: str
    location: str
    source_digest: str

    def __post_init__(self) -> None:
        """Require provenance for binary, deleted, generated, and ordinary units."""
        if (not isinstance(self.unit_id, str) or not self.unit_id.strip()
                or len(self.unit_id) > 128 or self.kind not in ("source", "relationship")
                or not isinstance(self.location, str) or not self.location.strip()
                or not _sha(self.source_digest)):
            raise MemoryError("invalid_work_unit")


class ReviewMemory:
    """Transactional coverage and finding-reference ledger in a trusted store."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Leave unrelated caller transactions untouched."""
        if connection.isolation_level is not None or connection.in_transaction:
            raise MemoryError("autocommit_connection_required")
        self.db = connection
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS review_scope (
            scope_key TEXT PRIMARY KEY, inventory_digest TEXT NOT NULL,
            manifest_digest TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_unit (
            scope_key TEXT NOT NULL, unit_key TEXT NOT NULL,
            sequence_index INTEGER NOT NULL, kind_label TEXT NOT NULL,
            location_label TEXT NOT NULL, source_digest TEXT NOT NULL,
            run_state TEXT NOT NULL, record_text TEXT,
            PRIMARY KEY (scope_key, unit_key)
        );
        CREATE TABLE IF NOT EXISTS review_observation (
            scope_key TEXT NOT NULL, unit_key TEXT NOT NULL,
            record_digest TEXT NOT NULL, record_text TEXT NOT NULL,
            PRIMARY KEY (scope_key, unit_key, record_digest)
        );
        """)

    def _scope(self, identity: ReviewIdentity) -> str:
        """Resolve only a pre-seeded review; never create state on a read."""
        key = _hash(asdict(identity))
        row = self.db.execute("SELECT manifest_digest FROM review_scope WHERE scope_key=?", (key,)).fetchone()
        if row is None:
            raise MemoryError("unknown_review")
        manifest = [dict(zip(("unit_id", "kind", "location", "source_digest"), unit))
                    for unit in self.db.execute(
                        "SELECT unit_key, kind_label, location_label, source_digest FROM review_unit "
                        "WHERE scope_key=? ORDER BY sequence_index", (key,))]
        if _hash(manifest) != row[0]:
            raise MemoryError("inventory_integrity_failed")
        return key

    def seed(self, identity: ReviewIdentity, units: tuple[WorkUnit, ...], *,
             inventory_digest: str) -> None:
        """Seal a trusted complete inventory; later drift requires a new review."""
        units = tuple(units)
        if (not _sha(inventory_digest) or not units
                or any(not isinstance(u, WorkUnit) for u in units)
                or len({u.unit_id for u in units}) != len(units)
                or not any(u.kind == "source" for u in units)):
            raise MemoryError("invalid_inventory")
        if not any(u.kind == "relationship" for u in units):
            raise MemoryError("relationship_inventory_required")
        key = _hash(asdict(identity))
        manifest = _hash([asdict(u) for u in units])
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT inventory_digest, manifest_digest FROM review_scope "
                                  "WHERE scope_key=?", (key,)).fetchone()
            if row is not None:
                if row != (inventory_digest, manifest):
                    raise MemoryError("inventory_changed")
            else:
                self.db.execute("INSERT INTO review_scope VALUES (?, ?, ?)", (key, inventory_digest, manifest))
                self.db.executemany("INSERT INTO review_unit VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL)",
                    [(key, u.unit_id, i, u.kind, u.location, u.source_digest) for i, u in enumerate(units)])
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def record(self, identity: ReviewIdentity, unit_id: str, source_digest: str, *,
               evidence_refs: tuple[str, ...], finding_refs: tuple[str, ...], status: str) -> None:
        """Record an observation without allowing later summaries to erase findings.

        A reviewed unit is sealed. A blocked unit may acquire further evidence;
        all earlier observation records and finding references remain available.
        These receipt hashes must be validated independently by the final gate.
        """
        evidence_refs, finding_refs = tuple(evidence_refs), tuple(finding_refs)
        if (status not in ("reviewed", "blocked") or not evidence_refs
                or any(not _sha(v) for v in evidence_refs + finding_refs)
                or len(set(evidence_refs)) != len(evidence_refs)
                or len(set(finding_refs)) != len(finding_refs)):
            raise MemoryError("invalid_receipt")
        key = self._scope(identity)
        record = json.dumps({"status": status, "evidence_refs": sorted(evidence_refs),
                             "finding_refs": sorted(finding_refs)}, sort_keys=True, separators=(",", ":"))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT source_digest, run_state, record_text FROM review_unit "
                                  "WHERE scope_key=? AND unit_key=?", (key, unit_id)).fetchone()
            if row is None:
                raise MemoryError("unknown_unit")
            if row[0] != source_digest:
                raise MemoryError("source_digest_mismatch")
            if row[1] == "reviewed" and row[2] != record:
                raise MemoryError("record_conflict")
            self.db.execute("INSERT OR IGNORE INTO review_observation VALUES (?, ?, ?, ?)",
                            (key, unit_id, _hash(record), record))
            self.db.execute("UPDATE review_unit SET run_state=?, record_text=? "
                            "WHERE scope_key=? AND unit_key=?", (status, record, key, unit_id))
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def pending(self, identity: ReviewIdentity, *, limit: int) -> tuple[dict, ...]:
        """Return a bounded next-work page, including blocked obligations."""
        _page_limit(limit)
        key = self._scope(identity)
        rows = self.db.execute("SELECT unit_key, kind_label, location_label, source_digest, run_state "
                               "FROM review_unit WHERE scope_key=? AND run_state!='reviewed' "
                               "ORDER BY sequence_index LIMIT ?", (key, limit)).fetchall()
        return tuple(dict(zip(("unit_id", "kind", "location", "source_digest", "status"), row)) for row in rows)

    def findings(self, identity: ReviewIdentity) -> tuple[str, ...]:
        """Keep the union of finding artifacts outside any lossy LLM reduction."""
        key = self._scope(identity)
        references = set()
        for (raw,) in self.db.execute("SELECT record_text FROM review_observation WHERE scope_key=?", (key,)):
            references.update(json.loads(raw)["finding_refs"])
        return tuple(sorted(references))

    def status(self, identity: ReviewIdentity) -> dict:
        """Report coverage separately from semantic review and approval authority."""
        key = self._scope(identity)
        counts = {(kind, state): n for kind, state, n in self.db.execute(
            "SELECT kind_label, run_state, COUNT(*) FROM review_unit WHERE scope_key=? "
            "GROUP BY kind_label, run_state", (key,))}
        total = sum(counts.values())
        remaining = sum(n for (kind, state), n in counts.items() if state != "reviewed")
        return {
            "total_units": total,
            "source_reviewed": counts.get(("source", "reviewed"), 0),
            "relationship_pending": sum(n for (kind, state), n in counts.items()
                                        if kind == "relationship" and state != "reviewed"),
            "blocked_units": sum(n for (kind, state), n in counts.items() if state == "blocked"),
            "pending_units": remaining,
            "finding_count": len(self.findings(identity)),
            "coverage_complete": total > 0 and remaining == 0,
            "approval_authorized": False,
        }

    def render(self, identity: ReviewIdentity, *, limit: int) -> str:
        """Generate memory.md as a paged index, never as a growing transcript."""
        state = self.status(identity)
        lines = ["# Review memory", f"Repository: {identity.repository} PR {identity.pr_number}",
                 f"Base: {identity.base_sha}", f"Head: {identity.head_sha}",
                 "This is a work index, not approval evidence.",
                 json.dumps(state, sort_keys=True), "Next work (untrusted labels, JSON quoted):"]
        for row in self.pending(identity, limit=limit):
            row = dict(row)
            # Display abbreviation only. The full location is retained in pending().
            row["location"] = row["location"][:160]
            lines.append(json.dumps(row, ensure_ascii=True, sort_keys=True))
        return "\n".join(lines) + "\n"


def _open_database(path: Path) -> sqlite3.Connection:
    """Require private storage; the launcher must separately establish provenance."""
    path = path.absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise MemoryError("untrusted_database_path")
    info, parent = path.stat(), path.parent.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600 or stat.S_IMODE(parent.st_mode) != 0o700
            or info.st_uid != os.getuid() or parent.st_uid != os.getuid()):
        raise MemoryError("untrusted_database_path")
    return sqlite3.connect("file:" + quote(str(path)) + "?mode=rw", uri=True, isolation_level=None)


def main(argv: list[str] | None = None) -> int:
    """Serve bounded local memory operations using JSON on standard input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("seed", "record", "status", "next", "memory", "findings"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--max-input-bytes", type=int, required=True)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    db = None
    try:
        _page_limit(args.limit)
        _page_limit(args.max_input_bytes)
        if args.offset < 0:
            raise MemoryError("invalid_offset")
        raw = sys.stdin.buffer.read(args.max_input_bytes + 1)
        if len(raw) > args.max_input_bytes:
            raise MemoryError("input_too_large")
        payload = json.loads(raw)
        identity = ReviewIdentity(**payload["identity"])
        db = _open_database(args.db)
        memory = ReviewMemory(db)
        if args.command == "seed":
            memory.seed(identity, tuple(WorkUnit(**u) for u in payload["units"]),
                        inventory_digest=payload["inventory_digest"])
            result = memory.status(identity)
        elif args.command == "record":
            memory.record(identity, payload["unit_id"], payload["source_digest"],
                          evidence_refs=tuple(payload["evidence_refs"]),
                          finding_refs=tuple(payload["finding_refs"]), status=payload["status"])
            result = memory.status(identity)
        elif args.command == "memory":
            sys.stdout.write(memory.render(identity, limit=args.limit))
            return 0
        elif args.command == "next":
            result = memory.pending(identity, limit=args.limit)
        elif args.command == "findings":
            result = memory.findings(identity)[args.offset:args.offset + args.limit]
        else:
            result = memory.status(identity)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        # Do not echo source-controlled locations, payloads, or database diagnostics.
        print("review_memory_failed:" + type(exc).__name__, file=sys.stderr)
        return 2
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
