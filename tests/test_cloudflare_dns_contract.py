import os
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def bash_executable() -> str:
    if os.name != "nt":
        return "bash"
    for candidate in (
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
    ):
        if candidate.exists():
            return str(candidate)
    return "bash"


def shell_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    drive = resolved.drive.rstrip(":").lower()
    tail = resolved.as_posix()[2:]
    return f"/{drive}{tail}"


def make_invalid_cloudflare_curl(tmp_path: Path) -> Path:
    curl = tmp_path / "curl"
    curl.write_text(
        """#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    shift
    out="$1"
  fi
  shift || true
done
printf '%s' '{"success":false,"errors":[{"code":1000,"message":"Invalid API Token"}]}' >"${out}"
printf '403'
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return curl


def make_cloudflare_jq_stub(tmp_path: Path) -> Path:
    jq = tmp_path / "jq"
    jq.write_text(
        """#!/bin/sh
expr=""
for arg in "$@"; do
  case "$arg" in
    -*) ;;
    *) expr="$arg" ;;
  esac
done
case "$expr" in
  ".success // false")
    printf 'false\\n'
    ;;
  ".errors // .")
    printf '[{"code":1000,"message":"Invalid API Token"}]\\n'
    ;;
  *)
    printf 'unsupported fake jq expression: %s\\n' "$expr" >&2
    exit 99
    ;;
esac
""",
        encoding="utf-8",
    )
    jq.chmod(0o755)
    return jq


def write_zones_config(tmp_path: Path) -> Path:
    config = tmp_path / "zones.json"
    config.write_text(
        """{"zones":[{"zone_name":"example.com","product_repo":"example","product_label":"Example","records":[]}]}""",
        encoding="utf-8",
    )
    return config


def run_reconcile(tmp_path: Path, mode: str, allow_soft_failure: str) -> subprocess.CompletedProcess[str]:
    make_invalid_cloudflare_curl(tmp_path)
    make_cloudflare_jq_stub(tmp_path)
    config = write_zones_config(tmp_path)
    command = " ".join(
        [
            f"PATH={shlex.quote(shell_path(tmp_path))}:$PATH",
            "CF_API_TOKEN=bad-token",
            "CF_ACCOUNT_ID=account-id",
            f"CF_MODE={shlex.quote(mode)}",
            f"CF_CONFIG={shlex.quote(shell_path(config))}",
            f"CF_ALLOW_DRY_RUN_TOKEN_FAILURE={shlex.quote(allow_soft_failure)}",
            f"GITHUB_STEP_SUMMARY={shlex.quote(shell_path(tmp_path / 'summary.md'))}",
            "bash infra/cloudflare/reconcile.sh",
        ]
    )
    return subprocess.run(
        [bash_executable(), "-lc", command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_push_dry_run_invalid_token_logs_reason_and_exits_zero(tmp_path: Path) -> None:
    result = run_reconcile(tmp_path, mode="dry-run", allow_soft_failure="true")

    assert result.returncode == 0
    assert "TOKEN_STATUS: INVALID" in result.stdout
    assert "(http 403)" in result.stdout
    assert "::warning::Cloudflare DNS dry-run skipped" in result.stdout
    assert "apply mode remains a hard failure" in result.stdout


def test_apply_invalid_token_remains_hard_failure(tmp_path: Path) -> None:
    result = run_reconcile(tmp_path, mode="apply", allow_soft_failure="true")

    assert result.returncode == 1
    assert "TOKEN_STATUS: INVALID" in result.stdout
    assert "(http 403)" in result.stdout
    assert "Aborting: cannot proceed without a valid API token." in result.stdout


def test_workflow_allows_only_push_dry_run_token_soft_failure() -> None:
    workflow = (ROOT / ".github/workflows/cloudflare-dns.yml").read_text(encoding="utf-8")

    assert "CF_ALLOW_DRY_RUN_TOKEN_FAILURE: ${{ github.event_name == 'push' && 'true' || 'false' }}" in workflow
