"""Behavioral contracts for the fixed, unprivileged Gyeot reusable CI lane."""

from pathlib import Path
import os
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/gyeot-ci.yml"
REPOSITORY = "ContextualWisdomLab/gyeot"


def workflow():
    """Load the actual workflow, with an explicit missing-feature assertion."""
    assert WORKFLOW.is_file(), "Missing central Gyeot reusable CI workflow"
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.mark.parametrize("job_name", ["verify", "server-verify"])
@pytest.mark.parametrize("event,source,target,status", [
    ("pull_request", REPOSITORY, REPOSITORY, 0),
    ("push", "", REPOSITORY, 0),
    ("workflow_dispatch", "", REPOSITORY, 0),
    ("pull_request", "foreign/fork", REPOSITORY, 1),
    ("pull_request", "", REPOSITORY, 1),
    ("pull_request", REPOSITORY + "-other", REPOSITORY, 1),
    ("pull_request_target", REPOSITORY, REPOSITORY, 1),
    ("repository_dispatch", "", REPOSITORY, 1),
    ("", "", REPOSITORY, 1),
    ("push", "", "foreign/gyeot", 1),
    ("workflow_dispatch", "", "", 1),
    ("pull_request", "foreign/fork", "foreign/fork", 1),
])
def test_source_admission_before_any_action(job_name, event, source, target, status):
    """Run the real first shell against admitted and rejected caller tuples."""
    job = workflow()["jobs"][job_name]
    assert "if" not in job
    step = job["steps"][0]
    assert step["shell"] == "bash" and "uses" not in step
    assert "${{" not in step["run"]
    assert step["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "SOURCE_REPOSITORY": "${{ github.event.pull_request.head.repo.full_name }}",
        "TARGET_REPOSITORY": "${{ github.repository }}",
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", step["run"]],
        env={"PATH": os.environ["PATH"], "EVENT_NAME": event,
             "SOURCE_REPOSITORY": source, "TARGET_REPOSITORY": target},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == status, result.stderr
    assert "continue-on-error" not in step


def test_fixed_reusable_contract_and_snapshot_wiring():
    """Require real supported contexts, fixed snapshots and credential-free checkouts."""
    import re
    data = workflow()
    assert data.get("on", data.get(True)) == {"workflow_call": None}
    assert data["permissions"] == {"contents": "read"}
    assert "concurrency" not in data
    text = WORKFLOW.read_text()
    assert "secrets." not in text and "inputs." not in text
    assert "job.workflow_" not in text and "github.workflow_sha" not in text
    for name, job in data["jobs"].items():
        assert job["runs-on"] == {"group": "CWL Gyeot CI", "labels": ["self-hosted", "Linux", "X64", "gyeot-ci"]}
        assert job["timeout-minutes"] == 30
        assert not any(key in job for key in ["concurrency", "permissions", "environment", "continue-on-error"])
        steps = job["steps"]
        checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
        assert len(checkouts) == 2
        assert checkouts[0]["with"]["repository"] == REPOSITORY
        assert checkouts[0]["with"]["ref"] == "${{ github.sha }}"
        assert checkouts[1]["with"]["repository"] == "ContextualWisdomLab/.github"
        assert checkouts[1]["with"]["ref"] == "${{ env.GYEOT_HELPER_COMMIT }}"
        assert "UNPUBLISHED_GYEOT_HELPER_COMMIT" in text
        for step in checkouts:
            assert step["with"]["persist-credentials"] is False
        for step in steps:
            assert "continue-on-error" not in step
            if "uses" in step:
                assert re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", step["uses"])
        node = next(s for s in steps if s.get("uses", "").startswith("actions/setup-node@"))
        assert node["with"]["node-version"] == "24"
        lane = "app" if name == "verify" else "server"
        verifier = next(s for s in steps if s.get("id") == f"{lane}_verification")
        assert verifier["run"] == f'bash central/scripts/ci/gyeot_verify_{lane}.sh "$GYEOT_SOURCE_ROOT"'
        assert verifier["env"]["GYEOT_SOURCE_ROOT"] == "${{ github.workspace }}/source"
        assert verifier["env"]["RUNNER_TEMP"] == "${{ runner.temp }}"


def test_unpublished_helper_pin_fails_before_central_checkout(tmp_path):
    """Reject a missing/mutable snapshot instead of assuming the caller SHA is central."""
    steps = workflow()["jobs"]["verify"]["steps"]
    step = next(s for s in steps if s.get("id") == "helper_pin")
    assert steps.index(step) < next(i for i, s in enumerate(steps) if s.get("id") == "central_checkout")
    for value, code in [("UNPUBLISHED_GYEOT_HELPER_COMMIT", 1), ("main", 1), ("", 1), ("a" * 40, 0), ("a" * 39, 1), ("A" * 40, 1)]:
        result = subprocess.run(["bash", "-c", step["run"]], env={"PATH": os.environ["PATH"], "GYEOT_HELPER_COMMIT": value}, capture_output=True)
        assert result.returncode == code


@pytest.mark.parametrize("defect,expected", [("clean", 0), ("wrong_sha", 1), ("foreign_origin", 1), ("modified", 1), ("missing", 1), ("symlink", 1)])
def test_snapshot_verification_rejects_invalid_helper_identity(tmp_path, defect, expected):
    """Execute actual identity shell with bounded synthetic Git results; no commit."""
    binary = tmp_path / "bin"
    write_executable(binary / "git", '''#!/usr/bin/env bash
set -euo pipefail
case "$*" in
 '-C central rev-parse HEAD') [[ "$DEFECT" != wrong_sha ]] && printf '%s\\n' "$PIN" || printf '%040d\\n' 0 ;;
 '-C central remote get-url origin') [[ "$DEFECT" != foreign_origin ]] && printf 'https://github.com/ContextualWisdomLab/.github.git\\n' || printf 'https://github.com/foreign/repo.git\\n' ;;
 '-C central diff --exit-code HEAD -- scripts/ci/') [[ "$DEFECT" != modified ]] || exit 1 ;;
 *) exit 99 ;;
esac
''')
    for name in ["gyeot_verify_app.sh", "gyeot_verify_server.sh", "gyeot_verify_export.sh", "gyeot_check_export.cjs"]:
        write_executable(tmp_path / "central/scripts/ci" / name, "synthetic bytes")
    target = tmp_path / "central/scripts/ci/gyeot_verify_app.sh"
    if defect == "missing":
        target.unlink()
    elif defect == "symlink":
        target.unlink()
        target.symlink_to("gyeot_verify_server.sh")
    step = next(s for s in workflow()["jobs"]["verify"]["steps"] if s.get("name") == "Verify fixed helper checkout identity")
    result = subprocess.run(["bash", "-c", step["run"]], cwd=tmp_path,
        env={"PATH":str(binary)+":"+os.environ["PATH"], "DEFECT":defect, "PIN":"a"*40, "GYEOT_HELPER_COMMIT":"a"*40}, capture_output=True)
    assert result.returncode == expected


def write_executable(path, text):
    """Create an explicitly synthetic tool in this attempt's private directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def permits_upload(condition, outcomes, ready):
    """Evaluate only the actual bounded coverage predicate; reject unknown terms."""
    import re
    for term in condition.split(" && "):
        if term == "always()":
            continue
        if term == "steps.app_verification.outputs.coverage_ready == 'true'":
            if ready != "true":
                return False
            continue
        match = re.fullmatch(r"steps\.([a-z_]+)\.outcome == 'success'", term)
        assert match, term
        if outcomes.get(match[1]) != "success":
            return False
    return True


@pytest.mark.parametrize("failure,expected,ready", [
    ("success", 0, True), ("node", 1, False), ("install", 23, False),
    ("policy_install", 23, False), ("policy_test", 23, False),
    ("actionlint", 23, False), ("typecheck", 23, False),
    ("jest_empty", 23, False), ("jest", 23, True), ("export", 23, True),
    ("symlink", 0, False), ("symlink_file", 0, False),
])
def test_app_attempt_keeps_coverage_attributed(tmp_path, failure, expected, ready):
    """Execute the central process with synthetic tools and seeded stale evidence."""
    helper = ROOT / "scripts/ci/gyeot_verify_app.sh"
    assert helper.is_file(), "Missing central app verification process"
    source = tmp_path / "source"
    source.mkdir()
    (source / "coverage").mkdir()
    (source / "coverage/stale").write_text("previous candidate")
    (source / "sentinel").write_text("preserve")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "lcov.info").write_text("previous foreign candidate")
    binary = tmp_path / "bin"
    write_executable(binary / "node", '''#!/usr/bin/env bash
if [[ "$1" == -p ]]; then
  [[ "$FAILURE" != node ]] && printf '24\\n' || printf '22\\n'
else
  exec "$REAL_NODE" "$@"
fi
''')
    write_executable(binary / "npm", '''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$TRACE"
case "$*" in
  'ci '*) [[ "$FAILURE" != install ]] || exit 23 ;;
  '--prefix .github ci '*) [[ "$FAILURE" != policy_install ]] || exit 23 ;;
  '--prefix .github test') [[ "$FAILURE" != policy_test ]] || exit 23 ;;
  'run typecheck') [[ "$FAILURE" != typecheck ]] || exit 23 ;;
  'test -- --ci --runInBand --coverage')
    [[ "$FAILURE" != jest_empty ]] || exit 23
    if [[ "$FAILURE" == symlink ]]; then ln -s "$OUTSIDE" coverage
    else
      mkdir coverage
      if [[ "$FAILURE" == symlink_file ]]; then ln -s "$OUTSIDE/lcov.info" coverage/lcov.info
      else printf 'current attempt\\n' > coverage/lcov.info; fi
    fi
    [[ "$FAILURE" != jest ]] || exit 23 ;;
  *) exit 99 ;;
esac
''')
    write_executable(binary / "actionlint", '#!/usr/bin/env bash\n[[ "$FAILURE" != actionlint ]] || exit 23\n')
    # Use a real Node checker against producer-shaped synthetic output.
    import shutil
    node = shutil.which("node")
    write_executable(source / "node_modules/.bin/expo", '''#!/usr/bin/env node
const fs = require('node:fs'); const path = require('node:path');
if (process.env.FAILURE === 'export') process.exit(23);
const p = process.argv[process.argv.indexOf('--platform')+1];
const d = process.argv[process.argv.indexOf('--output-dir')+1];
fs.mkdirSync(d,{recursive:true}); fs.writeFileSync(path.join(d,'bundle.hbc'),'bundle');
fs.writeFileSync(path.join(d,'metadata.json'),JSON.stringify({version:0,bundler:'metro',fileMetadata:{[p]:{bundle:'bundle.hbc',assets:[]}}}));
''')
    runner = tmp_path / "runner"
    runner.mkdir()
    output = tmp_path / "output"
    result = subprocess.run(["bash", str(helper), str(source)], cwd=tmp_path,
        env={"PATH": str(binary) + ":" + os.environ["PATH"], "FAILURE": failure,
             "RUNNER_TEMP": str(runner), "GITHUB_OUTPUT": str(output),
             "TRACE": str(tmp_path / "trace"), "REAL_NODE": node, "OUTSIDE": str(outside)},
        text=True, capture_output=True)
    assert result.returncode == expected, result.stderr
    assert output.read_text().splitlines()[0] == "coverage_ready=false"
    assert ("coverage_ready=true" in output.read_text()) == ready
    assert not (source / "coverage/stale").exists()
    assert (source / "sentinel").read_text() == "preserve"
    assert (outside / "lcov.info").read_text() == "previous foreign candidate"
    assert list(runner.iterdir()) == []
    upload = next(s for s in workflow()["jobs"]["verify"]["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
    outcomes = dict.fromkeys(["source_admission", "source_checkout", "central_checkout"], "success")
    assert permits_upload(upload["if"], outcomes, "true" if ready else "false") == ready
    for boundary in outcomes:
        failed = outcomes | {boundary: "failure"}
        assert not permits_upload(upload["if"], failed, "true")


@pytest.mark.parametrize("failure,expected", [("success",0),("install",23),("typecheck",23),("unit",23),("rls",23),("api",23),("migration",23)])
def test_server_process_preserves_serial_failures(tmp_path, failure, expected):
    """Run the real server wrapper with synthetic dependencies and SQL witnesses."""
    helper = ROOT / "scripts/ci/gyeot_verify_server.sh"
    assert helper.is_file(), "Missing central server verification process"
    source = tmp_path / "source"
    source.mkdir()
    binary = tmp_path / "bin"
    write_executable(binary / "node", "#!/usr/bin/env bash\nprintf '24\\n'\n")
    write_executable(binary / "id", "#!/usr/bin/env bash\nprintf '1001\\n'\n")
    for tool in ["initdb", "pg_ctl", "psql", "createdb"]:
        write_executable(binary / tool, "#!/usr/bin/env bash\nexit 0\n")
    write_executable(binary / "npm", '''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$TRACE"
case "$*" in
  '--prefix server ci '*) [[ "$FAILURE" != install ]] || exit 23 ;;
  '--prefix server run typecheck') [[ "$FAILURE" != typecheck ]] || exit 23 ;;
  '--prefix server run test:unit') [[ "$FAILURE" != unit ]] || exit 23 ;;
  *) exit 99 ;;
esac
''')
    for name, mode in [("test_rls", "rls"), ("test_server", "api"), ("test_migrations", "migration")]:
        write_executable(source / f"server/db/{name}.sh", f'#!/usr/bin/env bash\nset -euo pipefail\nprintf "{mode}\\n" >> "$TRACE"\n[[ "$FAILURE" != {mode} ]] || exit 23\n')
    result = subprocess.run(["bash", str(helper), str(source)], cwd=tmp_path,
        env={"PATH": str(binary)+":"+os.environ["PATH"], "TRACE": str(tmp_path/"trace"), "FAILURE": failure},
        text=True,capture_output=True)
    assert result.returncode == expected, result.stderr
    trace = (tmp_path / "trace").read_text().splitlines()
    full = ["--prefix server ci --include=dev --no-audit --no-fund", "--prefix server run typecheck", "--prefix server run test:unit", "rls", "api", "migration"]
    assert trace == full[:["install", "typecheck", "unit", "rls", "api", "migration"].index(failure)+1] if failure != "success" else trace == full


@pytest.mark.parametrize("platform", ["android", "ios"])
@pytest.mark.parametrize("failure", ["success", "command", "malformed", "missing_metadata", "missing_bundle", "empty_bundle", "wrong_platform", "wrong_bundler", "wrong_version", "non_js", "missing_assets", "bad_asset", "missing_asset", "traversal", "absolute", "windows", "symlink"])
def test_native_export_postconditions_and_cleanup(tmp_path, platform, failure):
    """Exercise both export commands with real checker and producer-shaped fixtures."""
    helper = ROOT / "scripts/ci/gyeot_verify_export.sh"
    assert helper.is_file(), "Missing central export verifier"
    source = tmp_path / "source"
    source.mkdir()
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "sentinel").write_text("preserve")
    outside = tmp_path / "outside.hbc"
    outside.write_text("foreign bundle")
    write_executable(source / "node_modules/.bin/expo", r"""#!/usr/bin/env node
const fs=require('node:fs'),path=require('node:path');
const p=process.argv[process.argv.indexOf('--platform')+1];
const d=process.argv[process.argv.indexOf('--output-dir')+1];
fs.appendFileSync(process.env.TRACE,p+'\n');
fs.mkdirSync(d,{recursive:true});
fs.writeFileSync(path.join(d,'bundle.hbc'),'bundle');
fs.writeFileSync(path.join(d,'asset.png'),'asset');
const m={version:0,bundler:'metro',fileMetadata:{[p]:{bundle:'bundle.hbc',assets:[{path:'asset.png',ext:'png'}]}}};
if(p===process.env.PLATFORM){
 const v=m.fileMetadata[p];
 switch(process.env.FAILURE){
 case 'command': process.exit(23);
 case 'malformed': fs.writeFileSync(path.join(d,'metadata.json'),'{bad');process.exit(0);
 case 'missing_metadata':process.exit(0);
 case 'missing_bundle':fs.unlinkSync(path.join(d,'bundle.hbc'));break;
 case 'empty_bundle':fs.writeFileSync(path.join(d,'bundle.hbc'),'');break;
 case 'wrong_platform':m.fileMetadata={web:v};break;
 case 'wrong_bundler':m.bundler='webpack';break;
 case 'wrong_version':m.version=1;break;
 case 'non_js':v.bundle='asset.png';break;
 case 'missing_assets':delete v.assets;break;
 case 'bad_asset':v.assets=[null];break;
 case 'missing_asset':fs.unlinkSync(path.join(d,'asset.png'));break;
 case 'traversal':v.bundle='../outside.hbc';break;
 case 'absolute':v.bundle=process.env.OUTSIDE;break;
 case 'windows':v.bundle='C:\\outside.hbc';break;
 case 'symlink':fs.unlinkSync(path.join(d,'bundle.hbc'));fs.symlinkSync(process.env.OUTSIDE,path.join(d,'bundle.hbc'));break;
 }
}
fs.writeFileSync(path.join(d,'metadata.json'),JSON.stringify(m));
""")
    trace = tmp_path / "trace"
    result = subprocess.run(["bash",str(helper),str(source)],cwd=tmp_path,
        env={"PATH":os.environ["PATH"],"RUNNER_TEMP":str(runner),"PLATFORM":platform,
             "FAILURE":failure,"OUTSIDE":str(outside),"TRACE":str(trace)},text=True,capture_output=True)
    assert result.returncode == (0 if failure=="success" else 23 if failure=="command" else 1), result.stderr
    assert trace.read_text().splitlines() == (["android","ios"] if platform=="ios" or failure=="success" else ["android"])
    assert [f.name for f in runner.iterdir()] == ["sentinel"]
    assert outside.read_text() == "foreign bundle"



@pytest.mark.parametrize("platform", ["android", "ios"])
def test_native_export_rejects_platform_root_symlink(tmp_path, platform):
    """Reject foreign output via actual shell/checker without deleting foreign bytes."""
    source = tmp_path / "source"
    source.mkdir()
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "sentinel").write_text("preserve runner")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "sentinel").write_text("preserve foreign")
    write_executable(source / "node_modules/.bin/expo", r"""#!/usr/bin/env node
const fs=require('node:fs'),path=require('node:path');
const p=process.argv[process.argv.indexOf('--platform')+1];
const d=process.argv[process.argv.indexOf('--output-dir')+1];
fs.appendFileSync(process.env.TRACE,p+'\n');
fs.writeFileSync(process.env.PRIVATE_ROOT,path.dirname(d));
if(p===process.env.PLATFORM) fs.symlinkSync(process.env.FOREIGN,d,'dir');
else fs.mkdirSync(d);
fs.writeFileSync(path.join(d,'bundle.hbc'),'synthetic bundle');
fs.writeFileSync(path.join(d,'metadata.json'),JSON.stringify({version:0,bundler:'metro',fileMetadata:{[p]:{bundle:'bundle.hbc',assets:[]}}}));
""")
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/ci/gyeot_verify_export.sh"), str(source)],
        cwd=tmp_path, env={"PATH": os.environ["PATH"], "RUNNER_TEMP": str(runner),
            "PLATFORM": platform, "FOREIGN": str(foreign),
            "TRACE": str(tmp_path / "trace"), "PRIVATE_ROOT": str(tmp_path / "private_root")},
        text=True, capture_output=True,
    )
    import json
    assert (foreign / "sentinel").read_text() == "preserve foreign"
    assert (foreign / "bundle.hbc").read_text() == "synthetic bundle"
    assert json.loads((foreign / "metadata.json").read_text())["fileMetadata"] == {
        platform: {"bundle": "bundle.hbc", "assets": []}}
    assert sorted(f.name for f in foreign.iterdir()) == ["bundle.hbc", "metadata.json", "sentinel"]
    assert [f.name for f in runner.iterdir()] == ["sentinel"]
    assert not Path((tmp_path / "private_root").read_text()).exists()
    assert result.returncode == 1, f"Accepted platform-root symlink: exit={result.returncode}; {result.stderr}"
    assert (tmp_path / "trace").read_text().splitlines() == (
        ["android"] if platform == "android" else ["android", "ios"])
    assert "Platform export root" in result.stderr


@pytest.mark.parametrize("platform", ["android", "ios"])
@pytest.mark.parametrize("admission", ["owned", "missing_owner", "foreign", "symlink", "wrong_platform", "parent_symlink", "owner_symlink"])
def test_direct_export_checker_requires_owned_platform_root(tmp_path, platform, admission):
    """Bind direct CLI root admission to a trusted private root before reading metadata."""
    import json
    owner = tmp_path / "private"
    owner.mkdir()
    output = owner / platform
    output.mkdir()
    trusted = owner
    if admission == "foreign":
        output = tmp_path / "foreign"
        output.mkdir()
    elif admission == "wrong_platform":
        output = owner / ("ios" if platform == "android" else "android")
        output.mkdir()
    elif admission == "symlink":
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        output.rmdir()
        output.symlink_to(foreign, target_is_directory=True)
    elif admission == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(owner, target_is_directory=True)
        output = alias / platform
    elif admission == "owner_symlink":
        trusted = tmp_path / "alias"
        trusted.symlink_to(owner, target_is_directory=True)
        output = trusted / platform
    (output / "bundle.hbc").write_text("synthetic bundle")
    (output / "metadata.json").write_text(json.dumps({"version": 0, "bundler": "metro",
        "fileMetadata": {platform: {"bundle": "bundle.hbc", "assets": []}}}))
    before = {f.name: f.read_bytes() for f in output.iterdir()}
    command = ["node", str(ROOT / "scripts/ci/gyeot_check_export.cjs"), str(output), platform]
    if admission != "missing_owner":
        command.append(str(trusted))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    assert {f.name: f.read_bytes() for f in output.iterdir()} == before
    assert result.returncode == (0 if admission == "owned" else 1), (
        f"Root admission {admission}: exit={result.returncode}; {result.stderr}")
    if admission != "owned":
        assert "export root" in result.stderr


def test_consumer_template_remains_unpublished_and_caller_only_concurrency():
    """Never install a consumer pointing at an unpublished or mutable central ref."""
    doc = ROOT / "docs/doctoring/gyeot-central-ci-20261008.md"
    assert doc.is_file(), "Missing consumer publication/runner handoff"
    import re
    block = re.search(r"```yaml\n(.*?)\n```", doc.read_text(), re.S)
    assert block
    caller = yaml.safe_load(block.group(1))
    assert caller["jobs"]["gyeot"]["uses"] == "ContextualWisdomLab/.github/.github/workflows/gyeot-ci.yml@UNPUBLISHED_CENTRAL_COMMIT"
    assert "secrets" not in caller["jobs"]["gyeot"]
    assert "with" not in caller["jobs"]["gyeot"]
    assert caller["permissions"] == {"contents": "read"}
    assert caller["concurrency"]["cancel-in-progress"] is True
    group = caller["concurrency"]["group"]
    for marker in ["github.repository", "github.workflow", "github.event.pull_request.number", "github.ref", "github.event_name"]:
        assert marker in group
    assert "github.sha" not in group
    assert caller.get("on",caller.get(True))["pull_request"] is None
    for marker in ["zero runners", "not remotely executed", "PR #2565", "Issue #2560", "UNPUBLISHED_GYEOT_HELPER_COMMIT"]:
        assert marker in doc.read_text()
