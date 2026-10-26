#!/usr/bin/env python3
"""Publish exact-head CodeQL SARIF via supported REST, retaining fail-closed custody.

This helper never posts statuses or wakes runs. Only the caller's Medium+ gate
and unchanged GHAS base/head identity proof can authorize those transitions.
A 202 upload is not completion. An authenticated job-log receipt is usable only
after rechecking the upload and analysis. Original bytes stay in an exclusive,
non-temporary self-hosted custody directory; no deletion/retention sweep exists.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PREFIX = "CWL_CODEQL_SARIF_RECEIPT "
SCHEMA = "cwl-codeql-sarif-v1"
MAX_BYTES = 64 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
LANGUAGES = {"actions", "c-cpp", "csharp", "go", "java-kotlin", "javascript-typescript", "python", "ruby", "rust", "swift"}


class PublicationError(RuntimeError):
    """Fixed, values-free error; never echo API diagnostics or bearer data."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Do not forward bearer headers on redirects."""
    def redirect_request(self, _request, _fp, _code, _message, _headers, _url):
        """Refuse every redirect."""
        return None


OPENER = urllib.request.build_opener(RejectRedirects())


def load_json(raw):
    """Reject malformed, duplicate-key and nonfinite evidence."""
    def pairs(items):
        """Preserve unique object membership."""
        out = {}
        for key, value in items:
            if key in out:
                raise PublicationError("duplicate evidence key")
            out[key] = value
        return out
    def constant(_value):
        """Reject nonfinite JSON numbers."""
        raise PublicationError("nonfinite evidence")
    def finite_float(value):
        """Reject exponent overflow as well as literal nonfinite constants."""
        number = float(value)
        if not math.isfinite(number):
            raise PublicationError("nonfinite evidence")
        return number
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)
    except (ValueError, UnicodeError) as exc:
        raise PublicationError("malformed evidence JSON") from exc


class GitHubAPI:
    """Single-attempt, fixed-origin REST actor; no mutation retry or token fallback."""
    def __init__(self, token):
        """Require a caller-provided target-scoped permission."""
        self.token = token

    def __call__(self, method, path, *, payload=None, accept="application/vnd.github+json"):
        """Use the documented public SARIF/analyses API only."""
        if not self.token:
            raise PublicationError("target security-events token missing")
        if (not isinstance(path, str) or re.fullmatch(
            r"repos/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/code-scanning/(?:sarifs(?:/[A-Za-z0-9_-]+)?|analyses(?:/[1-9][0-9]*|\?sarif_id=[A-Za-z0-9_-]+&per_page=100))", path
        ) is None or method not in {"GET", "POST"}):
            raise PublicationError("untrusted API endpoint")
        request = urllib.request.Request("https://api.github.com/" + path,
            data=json.dumps(payload, allow_nan=False).encode() if payload is not None else None,
            headers={"Accept": accept, "Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "cwl-codeql-sarif-publication"}, method=method)
        try:
            with OPENER.open(request, timeout=30) as response:
                expected = 202 if method == "POST" else 200
                if response.status != expected or response.headers.get("Link"):
                    raise PublicationError("unexpected API status or incomplete evidence")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise PublicationError("API evidence exceeds bound")
        except urllib.error.HTTPError as exc:
            exc.close()
            raise PublicationError("GitHub SARIF API HTTP refusal") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise PublicationError("GitHub SARIF API transport failed; no replay") from None
        return load_json(raw)


def validate_identity(identity):
    """Validate the admitted source/run/PR tuple before creating any request."""
    keys = {"repository", "pr_number", "base_sha", "head_sha", "language", "workflow_sha", "run_id", "run_attempt"}
    if not isinstance(identity, dict) or set(identity) != keys or any(type(x) is not str for x in identity.values()):
        raise PublicationError("invalid publication identity")
    if not re.fullmatch(r"ContextualWisdomLab/[A-Za-z0-9_.-]+", identity["repository"]) or identity["repository"].split("/")[1] in {".", ".."}:
        raise PublicationError("invalid target repository")
    for field in ("head_sha", "base_sha", "workflow_sha"):
        if not re.fullmatch(r"[a-f0-9]{40}", identity[field]):
            raise PublicationError("invalid commit identity")
    for field in ("pr_number", "run_id", "run_attempt"):
        if not re.fullmatch(r"[1-9][0-9]{0,19}", identity[field]):
            raise PublicationError("invalid run identity")
    if identity["language"] not in LANGUAGES:
        raise PublicationError("unsupported CodeQL language")


def category(identity):
    """Retain the existing per-language category, not a run-specific replacement."""
    return "/language:" + identity["language"]


def digest(raw):
    """Hash exact retained bytes."""
    return hashlib.sha256(raw).hexdigest()


def sync_directory(root):
    """Commit directory entries, propagating any durability failure."""
    dirfd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def save(root, name, raw):
    """Durably write an owned evidence file without following a leaf symlink."""
    path = root / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(root)


def save_receipt(root, receipt):
    """Write current custody state before and after the single POST."""
    save(root, "receipt.json", json.dumps(receipt, sort_keys=True, allow_nan=False).encode() + b"\n")


def prepare(raw, identity):
    """Normalize only absent automationDetails; never overwrite another category."""
    data = load_json(raw)
    if not isinstance(data, dict) or data.get("version") != "2.1.0" or not isinstance(data.get("runs"), list) or len(data["runs"]) != 1:
        raise PublicationError("one CodeQL SARIF run required per language")
    run = data["runs"][0]
    if not isinstance(run, dict) or run.get("tool", {}).get("driver", {}).get("name") != "CodeQL":
        raise PublicationError("CodeQL SARIF driver required")
    wanted = category(identity) + "/"
    details = run.get("automationDetails")
    if details is None:
        run["automationDetails"] = {"id": wanted}
    elif not isinstance(details, dict) or details.get("id") != wanted:
        raise PublicationError("conflicting CodeQL SARIF category")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def processing(api, endpoint, *, attempts, sleeper):
    """Bounded GET polling; partial/failed/unknown states cannot become accepted."""
    for attempt in range(attempts):
        data = api("GET", endpoint)
        if not isinstance(data, dict) or data.get("errors") not in (None, []):
            raise PublicationError("SARIF processing errors")
        state = data.get("processing_status")
        if state == "complete":
            return
        if state != "pending":
            raise PublicationError("SARIF processing failed or unknown")
        if attempt + 1 < attempts:
            sleeper(5)
    raise PublicationError("SARIF processing deadline exhausted")


def check_analysis(row, identity, sarif_id):
    """Require this exact upload, commit, PR ref, language and complete CodeQL data."""
    if not isinstance(row, dict):
        raise PublicationError("invalid code-scanning analysis")
    if (type(row.get("id")) is not int or row["id"] <= 0 or row.get("sarif_id") != sarif_id
        or row.get("commit_sha") != identity["head_sha"]
        or row.get("ref") != "refs/pull/" + identity["pr_number"] + "/head"
        or row.get("category") != category(identity)
        or not isinstance(row.get("analysis_key"), str) or not row["analysis_key"]
        or not isinstance(row.get("tool"), dict) or row["tool"].get("name") != "CodeQL"
        or row.get("error") != "" or row.get("warning") != ""):
        raise PublicationError("code-scanning analysis identity or completeness mismatch")


def publish(source, root, identity, *, api, checkout_uri, sleeper=time.sleep):
    """Retain original/upload/readback bytes and return only a fully processed receipt."""
    validate_identity(identity)
    paths = sorted(source.rglob("*.sarif"))
    if len(paths) != 1 or paths[0].is_symlink() or not paths[0].is_file() or not 0 < paths[0].stat().st_size <= MAX_BYTES:
        raise PublicationError("exactly one bounded SARIF file required")
    raw = paths[0].read_bytes()
    if not checkout_uri.startswith("file:///"):
        raise PublicationError("local checkout URI required")
    # Non-temporary host custody is exclusive to this run/attempt/language. A
    # repeated invocation fails before POST rather than replaying a lost ACK.
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise PublicationError("custody symlink refused")
    # Include the first existing (admitted durable) anchor: syncing a new
    # directory's contents alone does not persist its name in its parent.
    namespace_parents = [root.parent]
    while not namespace_parents[-1].exists():
        namespace_parents.append(namespace_parents[-1].parent)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=False)
    for parent in namespace_parents:
        sync_directory(parent)
    record = {"source_sha256": digest(raw)}
    receipt = {"schema": SCHEMA, "state": "prepared", "identity": identity,
               "minimum_retention_days": 7, "uploads": [record]}
    save(root, "source-0.sarif", raw)
    save_receipt(root, receipt)
    endpoint = "repos/" + identity["repository"] + "/code-scanning/"
    try:
        prepared = prepare(raw, identity)
        record["upload_sha256"] = digest(prepared)
        save(root, "upload-0.sarif", prepared)
        receipt["state"] = "post-intent"
        save_receipt(root, receipt)
        response = api("POST", endpoint + "sarifs", payload={
            "commit_sha": identity["head_sha"], "ref": "refs/pull/" + identity["pr_number"] + "/head",
            "sarif": base64.b64encode(gzip.compress(prepared, mtime=0)).decode(),
            "tool_name": "CodeQL", "checkout_uri": checkout_uri, "validate": True})
        sarif_id = response.get("id") if isinstance(response, dict) else None
        if not isinstance(sarif_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sarif_id) is None:
            raise PublicationError("invalid SARIF upload acknowledgement")
        record["sarif_id"] = sarif_id
        receipt["state"] = "accepted-not-processed"
        save_receipt(root, receipt)
        processing(api, endpoint + "sarifs/" + sarif_id, attempts=24, sleeper=sleeper)
        rows = api("GET", endpoint + "analyses?sarif_id=" + sarif_id + "&per_page=100")
        if not isinstance(rows, list) or len(rows) != 1:
            raise PublicationError("ambiguous or missing upload analysis")
        check_analysis(rows[0], identity, sarif_id)
        row = api("GET", endpoint + "analyses/" + str(rows[0]["id"]))
        check_analysis(row, identity, sarif_id)
        if row != rows[0]:
            raise PublicationError("analysis changed during readback")
        record["analysis_id"] = row["id"]
        record["analysis_key"] = row["analysis_key"]
        save(root, "analysis-0.json", json.dumps(row, sort_keys=True).encode())
        subset = api("GET", endpoint + "analyses/" + str(row["id"]), accept="application/sarif+json")
        if not isinstance(subset, dict) or subset.get("version") != "2.1.0" or not subset.get("runs"):
            raise PublicationError("processed SARIF evidence unavailable")
        subset_raw = json.dumps(subset, sort_keys=True).encode()
        save(root, "processed-0.sarif", subset_raw)
        record["processed_subset_sha256"] = digest(subset_raw)
        receipt["state"] = "complete"
        save_receipt(root, receipt)
        return receipt
    except Exception:
        receipt["state"] = "incomplete-no-replay"
        save_receipt(root, receipt)
        raise


def receipt_line(receipt):
    """Encode fixed-schema, bounded metadata only, never findings or credentials."""
    return PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":"))


def verify_log(log, identity, *, api):
    """Verify one authenticated job-log receipt against current API data, no writes."""
    validate_identity(identity)
    matches = []
    for line in log.splitlines():
        # gh job log GET includes an optional RFC3339 timestamp prefix. Anchor
        # the record, not a shell echo of the command printed by the runner.
        match = re.fullmatch(r"(?:[0-9T:.Z+-]+\s+)?" + re.escape(PREFIX) + r"(.{1,8192})", line)
        if match:
            matches.append(load_json(match.group(1)))
    if len(matches) != 1:
        raise PublicationError("missing or ambiguous durable SARIF receipt")
    receipt = matches[0]
    if (not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA
        or receipt.get("state") != "complete" or receipt.get("identity") != identity
        or receipt.get("minimum_retention_days") != 7
        or not isinstance(receipt.get("uploads"), list) or len(receipt["uploads"]) != 1):
        raise PublicationError("durable SARIF receipt identity mismatch")
    record = receipt["uploads"][0]
    for field in ("source_sha256", "upload_sha256", "processed_subset_sha256"):
        if not isinstance(record, dict) or re.fullmatch(r"[a-f0-9]{64}", str(record.get(field, ""))) is None:
            raise PublicationError("invalid SARIF custody digest")
    sid = record.get("sarif_id")
    aid = record.get("analysis_id")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sid) or type(aid) is not int or aid <= 0:
        raise PublicationError("invalid SARIF receipt reference")
    endpoint = "repos/" + identity["repository"] + "/code-scanning/"
    processing(api, endpoint + "sarifs/" + sid, attempts=1, sleeper=lambda _: None)
    row = api("GET", endpoint + "analyses/" + str(aid))
    check_analysis(row, identity, sid)
    if row["id"] != aid or row["analysis_key"] != record.get("analysis_key"):
        raise PublicationError("receipt analysis changed")
    return receipt


def verify_custody(root, identity, *, api):
    """Rehash all retained bytes before the established evidence step can pass."""
    receipt = load_json((root / "receipt.json").read_bytes())
    verify_log(receipt_line(receipt), identity, api=api)
    record = receipt["uploads"][0]
    for name, field in (("source-0.sarif", "source_sha256"),
                        ("upload-0.sarif", "upload_sha256"),
                        ("processed-0.sarif", "processed_subset_sha256")):
        path = root / name
        if path.is_symlink() or digest(path.read_bytes()) != record[field]:
            raise PublicationError("custody bytes changed")
    return receipt


def main(argv=None):
    """CLI run only from pinned trusted bytes under Python isolated mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("publish", "verify-log", "verify-custody"))
    parser.add_argument("--identity-env", action="store_true", required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--custody", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args(argv)
    identity = {key: os.environ.get(key.upper(), "") for key in (
        "repository", "pr_number", "base_sha", "head_sha", "language", "workflow_sha", "run_id", "run_attempt")}
    try:
        api = GitHubAPI(os.environ.get("GH_TOKEN", ""))
        if args.mode == "publish":
            if args.source is None or args.custody is None:
                raise PublicationError("source and exclusive custody required")
            receipt = publish(args.source, args.custody, identity, api=api,
                              checkout_uri=Path.cwd().resolve().as_uri() + "/")
            print(receipt_line(receipt), flush=True)
            summary = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary:
                with open(summary, "a", encoding="utf-8") as stream:
                    stream.write("\n### CodeQL target SARIF receipt\n```json\n" + json.dumps(receipt, sort_keys=True) + "\n```\n")
        elif args.mode == "verify-custody":
            if args.custody is None:
                raise PublicationError("custody required")
            verify_custody(args.custody, identity, api=api)
        else:
            if args.log is None or args.log.stat().st_size > MAX_RESPONSE:
                raise PublicationError("bounded job log required")
            verify_log(args.log.read_text(), identity, api=api)
        return 0
    except (PublicationError, OSError, ValueError, TypeError, AttributeError):
        print("::error::CodeQL SARIF publication/custody incomplete; no success or replay authorized.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
