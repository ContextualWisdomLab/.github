"""Execute supplier shell source; fixtures are not native runner isolation proof."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_tepp_tool_bootstrap import FOUNDATION, step_body

DIGEST = "dda7234360b7f578ca8b0ddcb80145646fa61a67c1720a5abc7051b35c9fcb71"
# Deliberately inert installer: no network or actual toolchain installation.
INSTALLER = b'''#!/bin/bash
set -e
printf 'install %s %s\\n' "$CARGO_HOME" "$RUSTUP_HOME" >>"$EVENTS"
[ "$FAIL_AT" != installer ] || exit 43
mkdir -p "$CARGO_HOME/bin" "$RUSTUP_HOME"
printf '#!/bin/bash\\nprintf "private-rustup\\\\n" >>"$EVENTS"\\n' >"$CARGO_HOME/bin/rustup"
chmod 755 "$CARGO_HOME/bin/rustup"
'''


class PrivateRustTests(unittest.TestCase):
    """Real digest checking and exclusive directories around an inert installer."""

    def execute(self, *, mismatch=False, fail_at="", missing_temp=False):
        """Run exact shell bytes with only the public download boundary replaced."""
        sha = shutil.which("gsha256sum") or shutil.which("sha256sum")
        if sha is None:
            self.fail("GNU sha256sum is a required test prerequisite")
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            for name in (".cargo", ".rustup"):
                (home / name).mkdir()
                (home / name / "sentinel").write_bytes(b"untouched")
            (home / ".cargo/bin").mkdir()
            old = home / ".cargo/bin/rustup"
            old.write_text('#!/bin/bash\nprintf "OLD\\n" >>"$EVENTS"\nexit 99\n')
            old.chmod(0o755)
            bins = root / "stands"
            bins.mkdir()
            (bins / "sha256sum").symlink_to(sha)
            fixture = root / "fixture"
            fixture.write_bytes(INSTALLER)
            curl = bins / "curl"
            curl.write_text('#!/bin/bash\nset -e\nprintf "fetch\\n" >>"$EVENTS"\n[ "$FAIL_AT" != curl ] || exit 43\nwhile [ "$#" -gt 0 ]; do\n if [ "$1" = --output ]; then shift; cp "$FIXTURE" "$1"; fi\n shift\ndone\n')
            curl.chmod(0o755)
            env = dict(os.environ, HOME=str(home), RUNNER_TEMP=str(root),
                       PATH=f"{bins}:{home}/.cargo/bin:/usr/bin:/bin", FIXTURE=str(fixture),
                       EVENTS=str(root / "events"), FAIL_AT=fail_at,
                       GITHUB_ENV=str(root / "env"), GITHUB_PATH=str(root / "path"),
                       CARGO_HOME=str(home / ".cargo"), RUSTUP_HOME=str(home / ".rustup"))
            if missing_temp:
                del env["RUNNER_TEMP"]
            script = step_body(FOUNDATION, "Bootstrap hash-verified Rustup")
            # Rebind only the pinned digest to known small fixture bytes, never bypass comparison.
            script = script.replace(DIGEST, "0" * 64 if mismatch else hashlib.sha256(INSTALLER).hexdigest())
            runs = []
            for _ in range(2):
                result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                                        env=env, capture_output=True, text=True, timeout=10)
                runs.append(result)
                if result.returncode:
                    break
            events = (root / "events").read_text() if (root / "events").exists() else ""
            exports = (root / "env").read_text() if (root / "env").exists() else ""
            paths = (root / "path").read_text() if (root / "path").exists() else ""
            for name in (".cargo", ".rustup"):
                self.assertEqual((home / name / "sentinel").read_bytes(), b"untouched")
            self.assertEqual(old.read_text(), '#!/bin/bash\nprintf "OLD\\n" >>"$EVENTS"\nexit 99\n')
            return runs, events, exports, paths, str(home), str(root)

    def test_positive_exclusive_private_homes_ignore_persistent_home(self):
        """Two same-job executions cannot reuse either inherited Rust home."""
        runs, events, exports, paths, home, root = self.execute()
        self.assertEqual([r.returncode for r in runs], [0, 0], [r.stderr for r in runs])
        self.assertNotIn(home, exports)
        self.assertNotIn(home, paths)
        self.assertNotIn("OLD", events)
        cargo = [line.split("=", 1)[1] for line in exports.splitlines() if line.startswith("CARGO_HOME=")]
        self.assertEqual(len(cargo), 2)
        self.assertEqual(len(set(cargo)), 2)
        self.assertTrue(all(path.startswith(root + "/tepp-rust-") for path in cargo))
        self.assertEqual(events.count("private-rustup"), 2)
        self.assertLess(events.index("fetch"), events.index("install"))
        self.assertLess(events.index("install"), events.index("private-rustup"))
        self.assertIn("OK", runs[0].stdout)

    def test_real_digest_mismatch_prevents_installer_and_exports(self):
        """GNU digest comparison rejects altered fixture bytes before execution."""
        runs, events, exports, paths, _, _ = self.execute(mismatch=True)
        self.assertNotEqual(runs[0].returncode, 0)
        self.assertIn("FAILED", runs[0].stdout)
        self.assertNotIn("install", events)
        self.assertEqual((exports, paths), ("", ""))

    def test_all_five_jobs_and_private_exports_precede_rust_consumers(self):
        """Keep all supplier gates; each Rust job publishes only its fresh home."""
        text = FOUNDATION.read_text().split("\njobs:\n", 1)[1]
        jobs = [line[2:-1] for line in text.splitlines()
                if line.startswith("  ") and not line.startswith("   ") and line.endswith(":")]
        self.assertEqual(jobs, ["repository-contracts", "rust-quality", "production-coverage", "live-postgres"])
        for index, job in enumerate(jobs[1:], 1):
            body = text.split(f"  {job}:\n", 1)[1]
            if index + 1 < len(jobs):
                body = body.split(f"\n  {jobs[index + 1]}:\n", 1)[0]
            bootstrap = body.index("- name: Bootstrap hash-verified Rustup")
            publish = body.index('>>"${GITHUB_PATH:?}"', bootstrap)
            install = body.index("rustup toolchain install", publish)
            self.assertLess(publish, install)
            self.assertNotIn("$HOME", body)
            self.assertNotIn("~/.cargo", body)
        docs = FOUNDATION.parent / "tepp-documentation-quality.yml"
        self.assertEqual(docs.read_text().count("  validate:\n"), 1)

    def test_private_version_guards_require_fresh_pinned_installations(self):
        """No restored executable is admitted; helpers must stay in the fresh home."""
        text = FOUNDATION.read_text()
        for tool in ("cargo-nextest", "cargo-deny", "cargo-llvm-cov"):
            self.assertNotIn('~/.cargo/bin/' + tool, text)
            self.assertIn('--root "$CARGO_HOME"', text)
        self.assertNotIn('uses: actions/cache@', text)
        self.assertNotIn('cache-hit', text)
        for tool, version in (("cargo-nextest", "CARGO_NEXTEST_VERSION"),
                              ("cargo-deny", "CARGO_DENY_VERSION"),
                              ("cargo-llvm-cov", "CARGO_LLVM_COV_VERSION")):
            self.assertIn(f'cargo install {tool} --root "$CARGO_HOME" --locked --version "${version}"', text)
        scripts = [step_body(FOUNDATION, "Verify pinned Rust quality tool versions"),
                   step_body(FOUNDATION, "Verify pinned cargo-llvm-cov version")]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            root = Path(directory)
            private = root / "private"
            (private / "bin").mkdir(parents=True)
            old = root / "old"
            old.mkdir()
            events = root / "events"
            versions = {"cargo-nextest": "0.9.140", "cargo-deny": "0.19.7", "cargo-llvm-cov": "0.8.6"}
            # Old cargo and helpers deliberately report all expected versions.
            for name in ("cargo", *versions):
                binary = old / name
                binary.write_text('#!/bin/bash\nprintf "OLD\\n" >>"$EVENTS"\nprintf "0.9.140 0.19.7 0.8.6\\n"\n')
                binary.chmod(0o755)
            env = dict(os.environ, PATH=f"{old}:/usr/bin:/bin", CARGO_HOME=str(private),
                       EVENTS=str(events), CARGO_NEXTEST_VERSION="0.9.140",
                       CARGO_DENY_VERSION="0.19.7", CARGO_LLVM_COV_VERSION="0.8.6")
            for state in ("missing", "partial", "wrong", "near_version", "nonzero", "correct", "with_metadata"):
                for binary in (private / "bin").iterdir():
                    binary.unlink()
                if state != "missing":
                    for name, version in versions.items():
                        if state == "partial" and name in ("cargo-deny", "cargo-llvm-cov"):
                            continue
                        reported = ("99.0.0" if state == "wrong" else
                                    version + ".99" if state == "near_version" else
                                    version + " (fixture metadata)" if state == "with_metadata" else version)
                        binary = private / "bin" / name
                        argv_guard = (
                            '[ "$1" = llvm-cov ] || { printf "expected llvm-cov subcommand\\n" >&2; exit 44; }\n'
                            if name == "cargo-llvm-cov" else ""
                        )
                        binary.write_text(f'#!/bin/bash\n{argv_guard}printf "{name} {reported}\\n"\nexit {43 if state == "nonzero" else 0}\n')
                        binary.chmod(0o755)
                for script in scripts:
                    result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                                            env=env, text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode == 0, state in ("correct", "with_metadata"), result.stderr)
                self.assertFalse(events.exists(), "version guard executed a persistent binary")

    def test_download_installer_and_missing_temp_fail_closed(self):
        """Failures never publish a half-installed private binary directory."""
        for failure in ("curl", "installer", "missing_temp"):
            with self.subTest(failure=failure):
                runs, events, exports, paths, _, _ = self.execute(
                    fail_at=failure, missing_temp=failure == "missing_temp")
                self.assertNotEqual(runs[0].returncode, 0)
                self.assertNotIn("private-rustup", events)
                self.assertEqual((exports, paths), ("", ""))


if __name__ == "__main__":
    unittest.main()
