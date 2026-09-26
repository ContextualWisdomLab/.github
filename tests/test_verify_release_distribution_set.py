from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.ci.verify_release_distribution_set import (
    DistributionSetError,
    verify_distribution_set,
)


SOURCE = "a" * 40
CONTROL = "b" * 40
RUN = 424242
ATTEMPT = 2
CREATED = "2026-09-26T12:01:00Z"
STARTED = "2026-09-26T12:00:00Z"


def _zip(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case() -> dict:
    rows = []
    archives = {}
    metadata = []
    record_lines = [
        f"# release v1.2.3 @ {SOURCE}, SOURCE_DATE_EPOCH=1",
        "target\tbyte_verified\tverification\tsha256\trebuild_sha256\tfile\tbuild_env",
    ]
    for index in range(1, 14):
        leg = "sdist" if index == 13 else f"target{index}-py3.12"
        filename = "pkg-1.2.3.tar.gz" if index == 13 else f"pkg-1.2.3-{index}.whl"
        name = "dist-sdist" if index == 13 else f"dist-wheel-{leg}"
        data = f"verified bytes for {leg}".encode()
        archive = _zip({filename: data})
        digest = "sha256:" + _sha(archive)
        archives[index] = archive
        metadata.append({"id": index, "name": name, "digest": digest,
                         "created_at": CREATED, "expired": False,
                         "workflow_run": {"id": RUN, "head_sha": CONTROL}})
        rows.append({"leg": leg, "file": filename, "sha256": _sha(data),
                     "artifact_id": index, "artifact_name": name,
                     "artifact_digest": digest})
        record_lines.append(f"{leg}\ttrue\tclean-target-repeat-same-env\t{_sha(data)}\t{_sha(data)}\t{filename}\trunner:x")
    manifest = {"schema_version": 1, "source_repository": "owner/repo",
                "source_sha": SOURCE, "control_sha": CONTROL, "run_id": RUN,
                "run_attempt": ATTEMPT, "distributions": rows}
    record = ("\n".join(record_lines) + "\n").encode()
    case = {"manifest": manifest, "record": record, "archives": archives,
            "metadata": metadata, "attempt": {"id": RUN, "run_attempt": ATTEMPT,
                                             "head_sha": CONTROL, "run_started_at": STARTED}}
    _repack_record(case)
    return case


def _repack_record(case: dict) -> None:
    archive = _zip({
        "reproducibility-record.tsv": case["record"],
        "release-scope-identities.json": b"[]\n",
        "release-scope-evidence-set.json": b"{}\n",
        "release-gate-distribution-set.json": (json.dumps(case["manifest"]) + "\n").encode(),
    })
    case["archives"][14] = archive
    entry = {"id": 14, "name": "reproducibility-record", "digest": "sha256:" + _sha(archive),
             "created_at": CREATED, "expired": False,
             "workflow_run": {"id": RUN, "head_sha": CONTROL}}
    case["metadata"] = [item for item in case["metadata"] if item["name"] != "reproducibility-record"] + [entry]


def _verify(case: dict, output: Path, *, wheel: str = "pkg-1.2.3-1.whl") -> list[dict]:
    record_digest = next(item["digest"] for item in case["metadata"] if item["name"] == "reproducibility-record")

    def fetch(repository: str, artifact_id: int, destination) -> None:
        assert repository == "owner/repo"
        destination.write(case["archives"][artifact_id])

    return verify_distribution_set(
        case["metadata"], case["attempt"], repository="owner/repo",
        source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT,
        record_artifact_id=14, record_artifact_digest=record_digest,
        wheel_filename=wheel, sdist_filename="pkg-1.2.3.tar.gz",
        fetch=fetch, output_dir=output,
    )


def test_verifies_all_thirteen_immutable_artifact_archives(tmp_path: Path) -> None:
    case = _case()
    verified = _verify(case, tmp_path / "dist")
    assert len(verified) == 13
    assert {path.name for path in (tmp_path / "dist").iterdir()} == {
        row["file"] for row in case["manifest"]["distributions"]
    }
    for row in verified:
        assert _sha((tmp_path / "dist" / row["file"]).read_bytes()) == row["sha256"]


def test_refuses_record_without_scope_evidence_set(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][14])) as original:
        members = {name: original.read(name) for name in original.namelist()
                   if name != "release-scope-evidence-set.json"}
    case["archives"][14] = _zip(members)
    case["metadata"][-1]["digest"] = "sha256:" + _sha(case["archives"][14])
    with pytest.raises(DistributionSetError, match="ZIP members differ"):
        _verify(case, tmp_path / "dist")


def test_cli_downloads_the_exact_ids_before_exposing_files(tmp_path: Path) -> None:
    case = _case()
    archives = tmp_path / "archives"
    archives.mkdir()
    for artifact_id, data in case["archives"].items():
        (archives / f"{artifact_id}.zip").write_bytes(data)
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("".join(json.dumps(item) + "\n" for item in case["metadata"]))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(case["attempt"]))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "path = sys.argv[2]\n"
        "sys.stdout.buffer.write((pathlib.Path(os.environ['FAKE_ARCHIVES']) / (path.split('/')[-2] + '.zip')).read_bytes())\n"
    )
    gh.chmod(0o755)
    script = Path(__file__).resolve().parents[1] / "scripts/ci/verify_release_distribution_set.py"
    record_digest = next(item["digest"] for item in case["metadata"] if item["name"] == "reproducibility-record")
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--repository", "owner/repo",
         "--source-sha", SOURCE, "--control-sha", CONTROL,
         "--run-id", str(RUN), "--run-attempt", str(ATTEMPT),
         "--record-artifact-id", "14", "--record-artifact-digest", record_digest,
         "--wheel-filename", "pkg-1.2.3-1.whl", "--sdist-filename", "pkg-1.2.3.tar.gz",
         "--metadata", str(metadata), "--attempt", str(attempt),
         "--output", str(tmp_path / "dist")],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "FAKE_ARCHIVES": str(archives)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["verified_distributions"]) == 13
    assert len(list((tmp_path / "dist").iterdir())) == 13


def test_refuses_forged_missing_stale_and_tampered_sets(tmp_path: Path) -> None:
    def missing(case):
        case["manifest"]["distributions"].pop()
        _repack_record(case)

    def wrong_source(case):
        case["manifest"]["source_sha"] = "c" * 40
        _repack_record(case)

    def wrong_run(case):
        case["metadata"][0]["workflow_run"]["id"] = 1

    def earlier_attempt(case):
        case["metadata"][0]["created_at"] = "2026-09-26T11:59:59Z"

    def tampered_zip(case):
        case["archives"][1] = _zip({case["manifest"]["distributions"][0]["file"]: b"altered"})

    def tampered_inner(case):
        case["archives"][1] = _zip({case["manifest"]["distributions"][0]["file"]: b"altered"})
        digest = "sha256:" + _sha(case["archives"][1])
        case["metadata"][0]["digest"] = digest
        case["manifest"]["distributions"][0]["artifact_digest"] = digest
        _repack_record(case)

    def duplicate_id(case):
        case["manifest"]["distributions"][1]["artifact_id"] = 1
        _repack_record(case)

    def extra_artifact(case):
        case["metadata"].append({**copy.deepcopy(case["metadata"][0]), "id": 100,
                                 "name": "dist-wheel-extra"})

    def wrong_attempt(case):
        case["attempt"]["run_attempt"] = 1

    for name, mutate in (
        ("missing", missing), ("wrong-source", wrong_source),
        ("wrong-run", wrong_run), ("earlier-attempt", earlier_attempt),
        ("tampered-zip", tampered_zip), ("tampered-inner", tampered_inner),
        ("duplicate-id", duplicate_id),
        ("extra-artifact", extra_artifact), ("wrong-attempt", wrong_attempt),
    ):
        case = _case()
        mutate(case)
        output = tmp_path / name
        with pytest.raises(DistributionSetError):
            _verify(case, output)
        assert not output.exists(), name

    with pytest.raises(DistributionSetError, match="selected wheel/sdist"):
        _verify(_case(), tmp_path / "foreign-pair", wheel="../../outside.whl")
    assert not (tmp_path / "foreign-pair").exists()
