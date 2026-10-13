"""Actual controller child composition with inert GitHub/model/HWP suppliers."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ci import premerge_review_tooling as caller

ROOT = Path(__file__).resolve().parents[1]


def composition(tmp_path, monkeypatch, scenario, attempt="1"):
    """Copy unchanged consumers and supply independently pinned synthetic context."""
    root = tmp_path / "tooling"
    entry = root / ".github/actions/noema-review/two_phase.py"
    entry.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / ".github/actions/noema-review/two_phase.py", entry)
    for source in (ROOT / "scripts/ci").glob("*.py"):
        target = root / "scripts/ci" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(ROOT / "scripts/ci/noema_hwp_mcp_reader.mjs", root / "scripts/ci/noema_hwp_mcp_reader.mjs")
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in root.rglob("*") if p.is_file()}
    manifest = {"schema_version": 1, "repository": "ContextualWisdomLab/.github",
                "commit": "c" * 40, "tree": "d" * 40,
                "entrypoint": ".github/actions/noema-review/two_phase.py", "files": files}
    scope = {"repository": "ContextualWisdomLab/example", "number": 7,
             "head": "a" * 40, "base": "b" * 40,
             "author": "writer", "reviewer": "cwl-noema-review[bot]"}
    reader = tmp_path / "reader"
    (reader / "dist/core").mkdir(parents=True)
    (reader / "dist/tools").mkdir()
    (reader / "node_modules/@rhwp/core").mkdir(parents=True)
    (reader / "package.json").write_text(json.dumps({"name": "hwp-mcp", "version": "0.3.0", "type": "module"}))
    (reader / "node_modules/@rhwp/core/package.json").write_text(json.dumps({"name": "@rhwp/core", "version": "0.7.7"}))
    (reader / "dist/core/document.js").write_text("export async function openDocument(p) { return p; } export function closeDocument(d) {}\n")
    (reader / "dist/tools/read.js").write_text("import {readFileSync} from 'node:fs'; export async function readHwp({file_path}) { return readFileSync(file_path, 'utf8'); }\n")
    node = Path(shutil.which("node")).resolve()
    assert node.name == "node"
    output = tmp_path / "step-output"
    output.touch(mode=0o600)
    context = {"GITHUB_OUTPUT": str(output), "NOEMA_TRANSPORT_RETRY_ATTEMPT": attempt,
               "NOEMA_HWP_MCP_SOURCE": str(reader), "NOEMA_NODE_EXECUTABLE": str(node),
               "node_sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
               "hwp_files": {p.relative_to(reader).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in reader.rglob("*") if p.is_file()}}
    admission = {"scope": scope, "installation_id": 7, "prepare_transport": context,
                 **{k: True for k in ("isolated_clean_job", "native_custody", "supplier_cost",
                                     "supplier_retention", "issuer_phase_separation")}}
    paths = {k: tmp_path / k for k in ("manifest", "admission", "issuer", "verdict")}
    paths["manifest"].write_text(json.dumps(manifest))
    paths["admission"].write_text(json.dumps(admission))
    paths["issuer"].write_text(json.dumps({"token": "SYNTHETIC_READ", "permissions": {
        "contents": "read", "metadata": "read", "pull_requests": "read"},
        "repositories": [{"full_name": scope["repository"]}]}))
    paths["issuer"].chmod(0o600)
    pr = {"base": {"sha": scope["base"], "repo": {"full_name": scope["repository"]}},
          "head": {"sha": scope["head"]}, "number": 7, "user": {"login": "writer"},
          "state": "open", "draft": False}
    real_run = subprocess.run
    children = []
    driver = '''import runpy,sys,socket,os
from pathlib import Path
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('external network forbidden'))
ns=runpy.run_path(sys.argv[1],run_name='fixture_two_phase')
g=ns['gate']
g.fetch_pr=lambda *a: {'headRefOid':'a'*40,'baseRefOid':'b'*40,'state':'OPEN','isDraft':False}
g.require_expected_head=lambda *a: None
g.current_actor=lambda: 'cwl-noema-review[bot]'
g.require_distinct_pr_author=lambda *a: 'writer'
g.existing_noema_review=lambda *a: False
g.fetch_diff=lambda *a: ('fixture',False)
g.fetch_changed_files=lambda *a: [('fixture.hwpx','modified')]
def context(*a):
 if sys.argv[2]=='hwp':
  from scripts.ci.noema_review_document import extract_review_document
  text=extract_review_document('fixture.hwpx',b'SYNTHETIC_DOCUMENT_TEXT')
  assert text=='SYNTHETIC_DOCUMENT_TEXT'
 return 'fixture'
g.build_review_context=context
def model(*a):
 if sys.argv[2]=='retry':
  raise g.NoemaTransportError('FIXTURE_CAPACITY_ONLY',capacity_unavailable=True,http_status=429,retry_after_seconds=60)
 return {'decision':'approve','summary':'FIXTURE_ONLY'}
g.call_llm=model
try: sys.exit(ns['main'](sys.argv[3:]))
except g.NoemaTransportError: sys.exit(1)
'''

    def boundary(command, **kwargs):
        """Stub metadata only; execute real child consumers without provider access."""
        if command[0] == "gh":
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(pr))
        children.append(dict(kwargs["env"]))
        actual = command[:3] + ["-c", driver, command[3], scenario] + command[4:]
        result = real_run(actual, **kwargs, capture_output=True, text=True, timeout=30)
        children[-1]["_fixture_stderr"] = result.stderr
        children[-1]["_fixture_stdout"] = result.stdout
        return result

    monkeypatch.setattr(caller.subprocess, "run", boundary)
    # load_noema_tooling's definition-time runner remains untouched; route only
    # its subprocess adapter to a real isolated child with inert external sinks.
    real_load = caller.load_noema_tooling
    monkeypatch.setattr(caller, "load_noema_tooling",
                        lambda *a, **kw: real_load(*a, **kw, child_runner=boundary))
    monkeypatch.setenv("LLM_GATEWAY_API_KEY", "SYNTHETIC_INFERENCE")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "ambient-output-not-accepted"))
    monkeypatch.setenv("NOEMA_TRANSPORT_RETRY_ATTEMPT", "0")
    monkeypatch.setenv("NODE_OPTIONS", "AMBIENT_LOADER_SENTINEL")
    args = ["--prepare-production", "--tooling-root", str(root),
            "--manifest", str(paths["manifest"]), "--accepted-digest", hashlib.sha256(paths["manifest"].read_bytes()).hexdigest(),
            "--admission", str(paths["admission"]), "--admission-digest", hashlib.sha256(paths["admission"].read_bytes()).hexdigest(),
            "--repo", scope["repository"], "--pr-number", "7", "--expected-head", scope["head"],
            "--phase-issuance", str(paths["issuer"]), "--verdict-file", str(paths["verdict"])]
    return args, paths, output, children, context


@pytest.mark.parametrize("attempt,eligible,next_attempt", [("1", "true", "2"), ("2", "false", None)])
def test_actual_child_preserves_capacity_output_and_bounded_retry(tmp_path, monkeypatch, attempt, eligible, next_attempt):
    """Real unchanged two_phase writes the accepted sink without resetting its bound."""
    args, paths, output, children, _ = composition(tmp_path, monkeypatch, "retry", attempt)
    assert caller.production_main(args) == 1
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values.get("transport_capacity_unavailable") == "true", children[0]["_fixture_stderr"]
    assert values["transport_retry_eligible"] == eligible
    assert values.get("transport_retry_next_attempt") == next_attempt
    assert children[0]["NOEMA_TRANSPORT_RETRY_ATTEMPT"] == attempt
    assert "NODE_OPTIONS" not in children[0]
    assert not paths["verdict"].exists()


def test_actual_child_hwp_consumer_receives_trusted_reader_and_node(tmp_path, monkeypatch):
    """Real document consumer and JS wrapper execute with synthetic package bodies."""
    args, paths, _, children, context = composition(tmp_path, monkeypatch, "hwp")
    assert caller.production_main(args) == 0, children[0]["_fixture_stderr"]
    assert paths["verdict"].exists()
    assert children[0]["NOEMA_HWP_MCP_SOURCE"] == context["NOEMA_HWP_MCP_SOURCE"]
    assert children[0]["NOEMA_NODE_EXECUTABLE"] == context["NOEMA_NODE_EXECUTABLE"]
    assert children[0]["PATH"] == "/usr/bin:/bin"
    assert "NODE_OPTIONS" not in children[0]
