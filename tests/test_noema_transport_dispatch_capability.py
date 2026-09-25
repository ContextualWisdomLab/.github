"""Keep Noema's capacity continuation on a scoped, usable dispatch credential."""

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


WORKFLOW = Path(".github/workflows/noema-review.yml")


def test_capacity_continuation_uses_separate_dispatch_job_and_live_head(tmp_path):
    """A failed review can dispatch once; stale or malformed targets cannot."""
    if shutil.which("jq") is None:
        pytest.skip("jq is required to execute the workflow's dispatch payload")

    workflow = WORKFLOW.read_text(encoding="utf-8")
    review = workflow.split("\n  noema-review:\n", 1)[1].split(
        "\n  noema-transport-redispatch:\n", 1
    )[0]
    dispatcher = workflow.split("\n  noema-transport-redispatch:\n", 1)[1]
    assert "transport_retry_eligible: ${{ steps.noema_prepare.outputs.transport_retry_eligible }}" in review
    assert "transport_capacity_unavailable: ${{ steps.noema_prepare.outputs.transport_capacity_unavailable }}" in review
    assert "contents: write" not in review.split("    steps:", 1)[0]
    assert "needs.noema-review.result == 'failure'" in dispatcher
    assert "needs.noema-review.outputs.transport_capacity_unavailable == 'true'" in dispatcher
    assert "needs.noema-review.outputs.transport_retry_eligible == 'true'" in dispatcher
    assert "contents: write" in dispatcher.split("    env:", 1)[0]
    assert "GH_TOKEN: ${{ github.token }}" in dispatcher
    assert "TARGET_REPOSITORY: ${{ github.repository }}" in dispatcher
    assert "NOEMA_REVIEW_TOKEN" not in dispatcher
    assert "actions/checkout" not in dispatcher

    script = textwrap.dedent(dispatcher.split("        run: |\n", 1)[1])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "assert os.environ['GH_TOKEN'] == 'dispatcher-token'\n"
        "args = sys.argv[1:]\n"
        "if args == ['api', 'repos/ContextualWisdomLab/example/pulls/7']:\n"
        "    print(json.dumps({'state': 'open', 'head': {'sha': os.environ['LIVE_SHA']}}))\n"
        "elif args == ['api', '-X', 'POST', 'repos/ContextualWisdomLab/example/dispatches', '--input', '-']:\n"
        "    with open(os.environ['DISPATCH_LOG'], 'a', encoding='utf-8') as log:\n"
        "        log.write(sys.stdin.read() + '\\n')\n"
        "else:\n"
        "    raise SystemExit('unexpected gh command: ' + repr(args))\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    head = "a" * 40
    log = tmp_path / "dispatches.jsonl"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_TOKEN": "dispatcher-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "PR_NUMBER": "7",
        "EXPECTED_HEAD_SHA": head,
        "LIVE_SHA": head,
        "CURRENT_ATTEMPT": "0",
        "NEXT_ATTEMPT": "1",
        "DELAY_SECONDS": "1",
        "PROVIDER_ATTEMPT_COUNT": "19",
        "TRANSPORT_HTTP_STATUS": "429",
        "DISPATCH_LOG": str(log),
    }

    def run(**updates):
        return subprocess.run(
            ["bash", "-e"], input=script, text=True, capture_output=True,
            env={**env, **updates}, check=False, timeout=20,
        )

    assert run().returncode == 0
    payload = json.loads(log.read_text(encoding="utf-8").strip())
    assert payload == {
        "event_type": "noema-review",
        "client_payload": {
            "target_repository": "ContextualWisdomLab/example",
            "pr_number": 7,
            "pr_head_sha": head,
            "transport_retry_attempt": 1,
        },
    }
    log.unlink()
    assert run(LIVE_SHA="b" * 40).returncode == 0
    assert not log.exists()
    assert run(NEXT_ATTEMPT="3").returncode != 0
    assert not log.exists()
    assert run(CURRENT_ATTEMPT="1").returncode != 0
    assert not log.exists()
