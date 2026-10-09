"""A full self-hosted runner disk must fail sidecar provisioning with a named cause."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci/contextual_orchestrator_review_sidecar.sh"


def _run(tmp_path: Path, available_kib: int) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "df").write_text(
        "#!/bin/sh\n"
        'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
        f'echo "/dev/vda1 100000000 1 {available_kib} 99% /"\n',
        encoding="utf-8",
    )
    (fake_bin / "df").chmod(0o755)
    # BSD chmod (macOS dev hosts) rejects "--"; GNU chmod on the runners accepts it.
    (fake_bin / "chmod").write_text(
        '#!/bin/bash\na=(); for x in "$@"; do [ "$x" = "--" ] || a+=("$x"); done\n'
        'exec /bin/chmod "${a[@]}"\n',
        encoding="utf-8",
    )
    (fake_bin / "chmod").chmod(0o755)
    # The assertions stop at the vendoring boundary; keep the test offline and
    # deterministic after that point.
    (fake_bin / "git").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (fake_bin / "git").chmod(0o755)
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path / "runner-temp"),
        "GITHUB_WORKSPACE": str(tmp_path / "workspace"),
    }
    (tmp_path / "runner-temp").mkdir()
    return subprocess.run(
        ["bash", str(SCRIPT), "--prepare"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_exhausted_runner_disk_fails_before_provisioning(tmp_path: Path) -> None:
    result = _run(tmp_path, available_kib=256 * 1024)
    assert result.returncode == 1
    assert "runner disk" in result.stderr
    assert "vendoring contextual-orchestrator" not in result.stdout


def test_low_runner_disk_warns_but_still_provisions(tmp_path: Path) -> None:
    result = _run(tmp_path, available_kib=1024 * 1024)
    assert "::warning::" in result.stdout and "runner disk" in result.stdout
    assert "vendoring contextual-orchestrator" in result.stdout


def test_sufficient_runner_disk_proceeds_to_provisioning(tmp_path: Path) -> None:
    result = _run(tmp_path, available_kib=50 * 1024 * 1024)
    assert "runner disk" not in result.stderr
    assert "vendoring contextual-orchestrator" in result.stdout
