"""Source tests for TEPP supplier tool bootstrap ordering."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FOUNDATION = ROOT / ".github/workflows/tepp-rust-foundation-ci.yml"
DOCS = ROOT / ".github/workflows/tepp-documentation-quality.yml"
PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
BASE = "9dab3c2a607ddef69b5ff8cb0f761e90f6bc28de"


def step_blocks(text: str) -> list[tuple[str, str]]:
    """Extract named multiline run steps from the actual workflow source."""
    lines = text.splitlines()
    result: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        if not line.startswith("      - name: "):
            continue
        name = line.removeprefix("      - name: ")
        run_index = index + 1
        while run_index < len(lines) and lines[run_index].startswith("        ") and lines[run_index].strip() != "run: |":
            run_index += 1
        if run_index >= len(lines) or lines[run_index].strip() != "run: |":
            continue
        body: list[str] = []
        for candidate in lines[run_index + 1 :]:
            if candidate and not candidate.startswith("          "):
                break
            body.append(candidate[10:] if candidate else "")
        result.append((name, "\n".join(body)))
    return result


def step_body(path: Path, name: str) -> str:
    """Return one action step body, failing closed if it is absent."""
    matches = [body for step, body in step_blocks(path.read_text()) if step == name]
    if not matches:
        raise AssertionError(f"missing {name!r} in {path}")
    if len(set(matches)) != 1:
        raise AssertionError(f"non-identical {name!r} bodies in {path}")
    return matches[0]


def run_with_stands(script: str, *, fail_at: str | None = None) -> tuple[int, str, str]:
    """Run an extracted action body with deterministic no-network command stands."""
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
        root = Path(directory)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        events = root / "events"
        stands = {
            "curl": '''#!/bin/bash
set -e
printf 'curl %s\\n' "$*" >>"$EVENTS"
if [ "$FAIL_AT" = curl ]; then exit 43; fi
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ] || [ "$1" = -o ]; then shift; destination="$1"; fi
  shift
done
cat >"$destination" <<'EOF'
#!/bin/bash
printf 'initializer %s\\n' "$*" >>"$EVENTS"
if [ "$FAIL_AT" = initializer ]; then exit 43; fi
mkdir -p "${CARGO_HOME:-$HOME/.cargo}/bin"
printf '#!/bin/bash\nexit 0\n' >"${CARGO_HOME:-$HOME/.cargo}/bin/rustup"
chmod 0755 "${CARGO_HOME:-$HOME/.cargo}/bin/rustup"
EOF
chmod 0755 "$destination"
''',
            "sha256sum": '''#!/bin/bash
set -e
printf 'sha256sum %s\\n' "$(cat)" >>"$EVENTS"
if [ "$FAIL_AT" = sha256sum ]; then exit 43; fi
''',
            "python3": '''#!/bin/bash
set -e
printf 'python3 %s\\n' "$*" >>"$EVENTS"
if [ "$FAIL_AT" = python3 ]; then exit 43; fi
if [ "$1" = -m ] && [ "$2" = venv ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python3"
fi
''',
        }
        for name, body in stands.items():
            path = bin_dir / name
            path.write_text(body)
            path.chmod(0o755)
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:/usr/bin:/bin",
            EVENTS=str(events),
            FAIL_AT=fail_at or "",
            RUNNER_TEMP=str(root),
            HOME=str(root),
            GITHUB_ENV=str(root / "github-env"),
            GITHUB_PATH=str(root / "github-path"),
        )
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
            capture_output=True, text=True, env=env, timeout=10,
        )
        return (
            result.returncode,
            events.read_text() if events.exists() else "",
            (root / "github-path").read_text() if (root / "github-path").exists() else "",
        )


class SupplierBootstrapTests(unittest.TestCase):
    """Exercise the action source and preserve the original gate inventory."""

    def test_pinned_setup_and_private_python_precede_consumers(self) -> None:
        """Every Python-bearing supplier job has an isolated interpreter first."""
        for path in (FOUNDATION, DOCS):
            text = path.read_text()
            self.assertIn(PYTHON_ACTION, text)
            self.assertIn('python-version: \'3.12\'', text)
            self.assertIn('python3 -m venv "${RUNNER_TEMP:?}/tepp-python-venv"', text)
            private = text.index("- name: Create private Python environment")
            consumers = [text.index(marker, private) for marker in (
                "python3 -m pip install",
                "python3 -m coverage",
                "python3 scripts/",
            ) if marker in text[private:]]
            self.assertTrue(consumers)
            self.assertLess(private, min(consumers))
            self.assertNotIn("break-system-packages", text)

    def test_rust_bootstrap_is_before_each_original_rust_install(self) -> None:
        """Each Rust job admits rustup before retaining its exact toolchain calls."""
        text = FOUNDATION.read_text()
        self.assertEqual(text.count("- name: Bootstrap hash-verified Rustup"), 3)
        for marker in (
            "rustup toolchain install 1.98.0 --profile minimal --component clippy --component rustfmt",
            "rustup toolchain install 1.98.0 --profile minimal --component llvm-tools-preview",
            "rustup toolchain install nightly-2026-08-21 --profile minimal --component llvm-tools-preview",
            "rustup toolchain install 1.98.0 --profile minimal",
        ):
            position = text.index(marker)
            self.assertLess(text.rfind("- name: Bootstrap hash-verified Rustup", 0, position), position)
        self.assertIn("--default-toolchain none --profile minimal --no-modify-path", text)
        self.assertIn("dda7234360b7f578ca8b0ddcb80145646fa61a67c1720a5abc7051b35c9fcb71", text)

    def test_positive_rust_order_comes_from_actual_action_body(self) -> None:
        """The synthetic stand-in proves fetch, hash, install, then export order."""
        code, events, exported = run_with_stands(step_body(FOUNDATION, "Bootstrap hash-verified Rustup"))
        self.assertEqual(code, 0)
        self.assertLess(events.index("curl "), events.index("sha256sum "))
        self.assertLess(events.index("sha256sum "), events.index("initializer "))
        self.assertIn("--default-toolchain none", events)
        self.assertIn("/.cargo/bin", exported)

    def test_negative_rust_controls_stop_before_later_actions(self) -> None:
        """Download, hash and installer failures remain terminal under pipefail."""
        script = step_body(FOUNDATION, "Bootstrap hash-verified Rustup")
        for failure in ("curl", "sha256sum", "initializer"):
            with self.subTest(failure=failure):
                code, events, exported = run_with_stands(script, fail_at=failure)
                self.assertEqual(code, 43)
                self.assertEqual(exported, "")
                if failure != "initializer":
                    self.assertNotIn("initializer ", events)

    def test_positive_and_negative_python_order_come_from_actual_action_body(self) -> None:
        """Private venv creation precedes pip verification and PATH publication."""
        script = step_body(FOUNDATION, "Create private Python environment")
        code, events, exported = run_with_stands(script)
        self.assertEqual(code, 0)
        self.assertLess(events.index("python3 -m venv"), events.index("python3 -m pip --version"))
        self.assertIn("tepp-python-venv/bin", exported)
        code, events, exported = run_with_stands(script, fail_at="python3")
        self.assertEqual(code, 43)
        self.assertNotIn("-m pip --version", events)
        self.assertEqual(exported, "")

    def test_original_step_bodies_are_retained(self) -> None:
        """Only named bootstrap steps are added; original run bodies stay exact."""
        for relative in (".github/workflows/tepp-rust-foundation-ci.yml", ".github/workflows/tepp-documentation-quality.yml"):
            current = dict(step_blocks((ROOT / relative).read_text()))
            original = subprocess.check_output(["git", "show", f"{BASE}:{relative}"], cwd=ROOT, text=True)
            original_steps = dict(step_blocks(original))
            for name, body in original_steps.items():
                if name == "Verify pinned Rust quality tool versions":
                    # Executed against missing/wrong/valid private tools by PrivateRustTests.
                    self.assertIn('"$CARGO_HOME/bin/cargo-nextest" --version', current[name])
                    self.assertIn('"$CARGO_HOME/bin/cargo-deny" --version', current[name])
                else:
                    self.assertEqual(current[name].replace(' --root "$CARGO_HOME"', ""), body, name)
            # Retain every original single-line gate and toolchain pin verbatim;
            # only explicit private install-root and version admission may change.
            for line in original.splitlines():
                if not line.startswith("        run: ") or line.strip() == "run: |":
                    continue
                if "cargo llvm-cov --version" in line:
                    self.assertIn('"$CARGO_HOME/bin/cargo-llvm-cov" --version', (ROOT / relative).read_text())
                elif "cargo install cargo-llvm-cov" in line:
                    self.assertIn(line.replace(" --locked", ' --root "$CARGO_HOME" --locked'), (ROOT / relative).read_text())
                else:
                    self.assertIn(line, (ROOT / relative).read_text())


if __name__ == "__main__":
    unittest.main()
