#!/usr/bin/env python3
"""One-shot source transformer for PR #1589 trusted Noema CodeGraph wiring.

This file is removed by its own successful transformation commit and is not a
production mechanism.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"expected exactly one replacement anchor in {path}; observed {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    gate_path = "scripts/ci/noema_review_gate.py"
    replace_once(
        gate_path,
        "import socket\nimport subprocess\n",
        "import socket\nimport stat\nimport subprocess\n",
    )
    replace_once(
        gate_path,
        "MAX_THREAD_BODY_CHARS = 1200\n",
        "MAX_THREAD_BODY_CHARS = 1200\nMAX_CODEGRAPH_CONTEXT_CHARS = 20000\n",
    )
    loader = dedent(
        '''\
        def load_codegraph_context(expected_head_sha: str) -> str:
            """Load trusted structural evidence and bind it to the reviewed exact head.

            The workflow writes this file under ``runner.temp`` after indexing a
            credential-free PR-source clone. When the workflow declares the context
            required, absence, a non-regular target, an oversized packet, or a stale
            head marker fails closed before model execution.
            """
            required_value = os.environ.get("NOEMA_REQUIRE_CODEGRAPH_CONTEXT", "").strip()
            if required_value not in {"", "0", "1"}:
                raise RuntimeError("NOEMA_REQUIRE_CODEGRAPH_CONTEXT must be 0 or 1")
            required = required_value == "1"
            context_path = os.environ.get("NOEMA_CODEGRAPH_CONTEXT_PATH", "").strip()
            if not context_path:
                if required:
                    raise RuntimeError("Required Noema CodeGraph context path was not configured")
                return ""
            if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_head_sha):
                raise RuntimeError("Noema CodeGraph context requires a canonical exact head SHA")
            if not hasattr(os, "O_NOFOLLOW"):
                raise RuntimeError("Noema CodeGraph context requires no-follow file access")

            try:
                descriptor = os.open(context_path, os.O_RDONLY | os.O_NOFOLLOW)
            except OSError as exc:
                if required:
                    raise RuntimeError("Required Noema CodeGraph context was unavailable") from exc
                return ""
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise RuntimeError("Noema CodeGraph context was not a regular file")
                with os.fdopen(descriptor, "r", encoding="utf-8", errors="replace") as handle:
                    descriptor = -1
                    text = handle.read(MAX_CODEGRAPH_CONTEXT_CHARS + 1)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

            if len(text) > MAX_CODEGRAPH_CONTEXT_CHARS:
                raise RuntimeError("Noema CodeGraph context exceeded its bounded evidence budget")
            if "# Trusted CodeGraph current-head evidence" not in text:
                raise RuntimeError("Noema CodeGraph context was missing its trusted evidence marker")
            match = re.search(
                r"(?m)^- Head SHA: `([0-9a-fA-F]{40})`\\s*$",
                text,
            )
            if match is None:
                raise RuntimeError("Noema CodeGraph context was missing its exact-head marker")
            if match.group(1).lower() != expected_head_sha.lower():
                raise RuntimeError("CodeGraph context head does not match the pull request head")
            return text.strip()


        '''
    )
    replace_once(gate_path, "def build_review_context(\n", loader + "def build_review_context(\n")
    replace_once(
        gate_path,
        '    """Build bounded non-diff context from review threads and changed files."""\n'
        "    sections: list[str] = []\n"
        "    threads = review_thread_context(pr)\n",
        '    """Build bounded non-diff context from trusted structural and source evidence."""\n'
        "    sections: list[str] = []\n"
        '    codegraph = load_codegraph_context(str(pr.get("headRefOid") or ""))\n'
        "    if codegraph:\n"
        '        sections.append("## CodeGraph context\\n" + codegraph)\n'
        "    threads = review_thread_context(pr)\n",
    )

    helper = dedent(
        r'''\
        #!/usr/bin/env bash
        set -euo pipefail

        : "${TARGET_REPOSITORY:?TARGET_REPOSITORY is required}"
        : "${PR_NUMBER:?PR_NUMBER is required}"
        : "${EXPECTED_HEAD_SHA:?EXPECTED_HEAD_SHA is required}"
        : "${PR_BASE_SHA:?PR_BASE_SHA is required}"
        : "${NOEMA_CODEGRAPH_CONTEXT_PATH:?NOEMA_CODEGRAPH_CONTEXT_PATH is required}"
        : "${GH_TOKEN:?GH_TOKEN is required for source materialization}"

        if ! [[ "$TARGET_REPOSITORY" =~ ^ContextualWisdomLab/[A-Za-z0-9_.-]+$ ]] ||
          ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] ||
          ! [[ "$EXPECTED_HEAD_SHA" =~ ^[0-9a-fA-F]{40}$ ]] ||
          ! [[ "$PR_BASE_SHA" =~ ^[0-9a-fA-F]{40}$ ]]; then
          echo "::error::Noema CodeGraph source metadata is malformed."
          exit 1
        fi

        CODEGRAPH_TRUSTED_ROOT="${RUNNER_TEMP:?}/trusted-noema-codegraph"
        source_root="${RUNNER_TEMP}/noema-codegraph-pr-source"
        askpass="${RUNNER_TEMP}/noema-codegraph-askpass.sh"
        rm -rf "$CODEGRAPH_TRUSTED_ROOT" "$source_root"
        rm -f "$NOEMA_CODEGRAPH_CONTEXT_PATH" "$askpass"
        mkdir -p "$CODEGRAPH_TRUSTED_ROOT" "$source_root"

        cat >"$askpass" <<'ASKPASS'
        #!/usr/bin/env bash
        set -euo pipefail
        case "${1:-}" in
          *Username*) printf '%s\n' x-access-token ;;
          *) printf '%s\n' "${GH_TOKEN:?}" ;;
        esac
        ASKPASS
        chmod 0700 "$askpass"

        git -C "$source_root" init -q
        git -C "$source_root" remote add origin "https://github.com/${TARGET_REPOSITORY}.git"
        GIT_ASKPASS="$askpass" GIT_ASKPASS_REQUIRE=force GIT_TERMINAL_PROMPT=0 \
          git -C "$source_root" fetch --no-tags --depth=1 origin "refs/pull/${PR_NUMBER}/head"
        observed_head="$(git -C "$source_root" rev-parse FETCH_HEAD)"
        if [ "${observed_head,,}" != "${EXPECTED_HEAD_SHA,,}" ]; then
          echo "::error::Noema CodeGraph PR ref is stale; expected ${EXPECTED_HEAD_SHA}, observed ${observed_head}."
          exit 1
        fi
        git -C "$source_root" update-ref refs/noema/head "$observed_head"
        GIT_ASKPASS="$askpass" GIT_ASKPASS_REQUIRE=force GIT_TERMINAL_PROMPT=0 \
          git -C "$source_root" fetch --no-tags --depth=1 origin "$PR_BASE_SHA"
        observed_base="$(git -C "$source_root" rev-parse FETCH_HEAD)"
        if [ "${observed_base,,}" != "${PR_BASE_SHA,,}" ]; then
          echo "::error::Noema CodeGraph base ref did not materialize at the expected SHA."
          exit 1
        fi
        git -C "$source_root" update-ref refs/noema/base "$observed_base"
        git -C "$source_root" checkout -q --detach refs/noema/head
        rm -f "$askpass"
        unset GH_TOKEN GITHUB_TOKEN ACTIONS_ID_TOKEN_REQUEST_TOKEN ACTIONS_ID_TOKEN_REQUEST_URL ACTIONS_RUNTIME_TOKEN

        for manifest in \
          "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package.json" \
          "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package-lock.json"; do
          if [ ! -f "$manifest" ] || [ -L "$manifest" ]; then
            echo "::error::Trusted Noema CodeGraph package input is missing or symlinked: $manifest"
            exit 1
          fi
        done
        cp "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package.json" \
          "$GITHUB_WORKSPACE/scripts/ci/codegraph-package/package-lock.json" \
          "$CODEGRAPH_TRUSTED_ROOT"/
        (
          cd "$CODEGRAPH_TRUSTED_ROOT"
          NPM_CONFIG_IGNORE_SCRIPTS=true npm ci --ignore-scripts --omit=dev --no-audit --no-fund
          NPM_CONFIG_IGNORE_SCRIPTS=true npm audit --package-lock-only --omit=dev --audit-level=moderate
        )

        PATCHED_PICOMATCH_DIR="$CODEGRAPH_TRUSTED_ROOT/node_modules/picomatch"
        patched_picomatch_version="$(
          node -e 'const fs=require("fs"); console.log(JSON.parse(fs.readFileSync(process.argv[1], "utf8")).version)' \
            "$PATCHED_PICOMATCH_DIR/package.json"
        )"
        if [ "$patched_picomatch_version" != "4.0.4" ]; then
          echo "::error::Trusted Noema CodeGraph hardening requires picomatch 4.0.4; found ${patched_picomatch_version:-missing}."
          exit 1
        fi

        mapfile -t codegraph_platforms < <(
          find "$CODEGRAPH_TRUSTED_ROOT/node_modules/@colbymchenry" \
            -mindepth 1 -maxdepth 1 -type d -name 'codegraph-*' -print
        )
        hardened_bundle_count=0
        for codegraph_platform in "${codegraph_platforms[@]}"; do
          bundled_picomatch="$codegraph_platform/lib/node_modules/picomatch"
          bundled_lock="$codegraph_platform/lib/node_modules/.package-lock.json"
          [ -d "$bundled_picomatch" ] || continue
          resolved_bundle="$(realpath "$bundled_picomatch")"
          case "$resolved_bundle" in
            "$CODEGRAPH_TRUSTED_ROOT"/node_modules/@colbymchenry/codegraph-*/lib/node_modules/picomatch) ;;
            *)
              echo "::error::Refusing to harden CodeGraph outside the trusted package root: $resolved_bundle"
              exit 1
              ;;
          esac
          if [ ! -f "$bundled_lock" ]; then
            echo "::error::CodeGraph platform bundle is missing its nested dependency lock: $bundled_lock"
            exit 1
          fi
          rm -rf "$bundled_picomatch"
          mkdir -p "$bundled_picomatch"
          cp -R "$PATCHED_PICOMATCH_DIR"/. "$bundled_picomatch"/
          patched_lock="$(mktemp)"
          jq --slurpfile trusted_lock "$CODEGRAPH_TRUSTED_ROOT/package-lock.json" \
            '.packages["node_modules/picomatch"] = $trusted_lock[0].packages["node_modules/picomatch"]' \
            "$bundled_lock" >"$patched_lock"
          mv "$patched_lock" "$bundled_lock"
          installed_version="$(
            node -e 'const fs=require("fs"); console.log(JSON.parse(fs.readFileSync(process.argv[1], "utf8")).version)' \
              "$bundled_picomatch/package.json"
          )"
          locked_version="$(jq -r '.packages["node_modules/picomatch"].version // empty' "$bundled_lock")"
          if [ "$installed_version" != "4.0.4" ] || [ "$locked_version" != "4.0.4" ]; then
            echo "::error::Noema CodeGraph nested picomatch hardening failed."
            exit 1
          fi
          hardened_bundle_count=$((hardened_bundle_count + 1))
        done
        if [ "$hardened_bundle_count" -lt 1 ]; then
          echo "::error::No installed CodeGraph platform bundle exposed a nested picomatch package to harden."
          exit 1
        fi

        CODEGRAPH_BIN="$CODEGRAPH_TRUSTED_ROOT/node_modules/.bin/codegraph"
        test -x "$CODEGRAPH_BIN"
        export CODEGRAPH_NO_DOWNLOAD=1
        codegraph_status="$(mktemp)"
        codegraph_raw="$(mktemp)"
        changed_scope="$(git -C "$source_root" diff --name-only refs/noema/base refs/noema/head | sed -n '1,80p' | tr '\n' ' ')"
        cd "$source_root"
        "$CODEGRAPH_BIN" init -i
        if ! "$CODEGRAPH_BIN" status >"$codegraph_status" 2>&1; then
          cat "$codegraph_status" >&2
          echo "::error::Noema CodeGraph status failed."
          exit 1
        fi
        if ! timeout 120s "$CODEGRAPH_BIN" explore \
          "Review blast radius, callers/callees, dependency paths, authority boundaries, state transitions, and focused tests for these exact-head changed files: ${changed_scope}" \
          >"$codegraph_raw" 2>&1; then
          cat "$codegraph_raw" >&2
          echo "::error::Noema CodeGraph changed-scope exploration failed."
          exit 1
        fi
        {
          printf '# Trusted CodeGraph current-head evidence\n\n'
          printf -- '- Head SHA: `%s`\n' "$EXPECTED_HEAD_SHA"
          printf -- '- Base SHA: `%s`\n\n' "$PR_BASE_SHA"
          printf '## CodeGraph status\n\n'
          head -c 3000 "$codegraph_status"
          printf '\n\n## Changed-scope exploration\n\n'
          head -c 15000 "$codegraph_raw"
        } >"$NOEMA_CODEGRAPH_CONTEXT_PATH"
        rm -f "$codegraph_status" "$codegraph_raw"
        test -s "$NOEMA_CODEGRAPH_CONTEXT_PATH"
        '''
    )
    Path("scripts/ci/noema_codegraph_context.sh").write_text(helper, encoding="utf-8")

    workflow_path = ".github/workflows/noema-review.yml"
    step = dedent(
        '''\
              - name: Materialize trusted Noema CodeGraph evidence
                if: env.PR_NUMBER != ''
                env:
                  GH_TOKEN: ${{ secrets.NOEMA_REVIEW_TOKEN || steps.noema_github_app_token.outputs.token || steps.noema_oidc_token.outputs.token }}
                  PR_BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.client_payload.pr_base_sha || '' }}
                  NOEMA_CODEGRAPH_CONTEXT_PATH: ${{ runner.temp }}/noema-codegraph-evidence.md
                  NOEMA_REQUIRE_CODEGRAPH_CONTEXT: "1"
                run: |
                  set -euo pipefail
                  if [ -z "${PR_BASE_SHA:-}" ]; then
                    PR_BASE_SHA="$(gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}" --jq '.base.sha // empty')"
                    export PR_BASE_SHA
                  fi
                  bash "$GITHUB_WORKSPACE/scripts/ci/noema_codegraph_context.sh"

        '''
    )
    replace_once(
        workflow_path,
        "      - name: Provision contextual-orchestrator review sidecar\n",
        step + "      - name: Provision contextual-orchestrator review sidecar\n",
    )
    replace_once(
        workflow_path,
        "          NOEMA_REVIEW_INSTALLATION_ID: ${{ steps.noema_github_app_token.outputs['installation-id'] }}\n        run: |\n",
        "          NOEMA_REVIEW_INSTALLATION_ID: ${{ steps.noema_github_app_token.outputs['installation-id'] }}\n"
        "          NOEMA_CODEGRAPH_CONTEXT_PATH: ${{ runner.temp }}/noema-codegraph-evidence.md\n"
        '          NOEMA_REQUIRE_CODEGRAPH_CONTEXT: "1"\n'
        "        run: |\n",
    )

    codegraph_test = dedent(
        '''\
        """Contracts for trusted CodeGraph evidence in the independent Noema reviewer."""

        from __future__ import annotations

        from pathlib import Path

        import pytest

        from scripts.ci import noema_review_gate as gate


        ROOT = Path(__file__).resolve().parents[1]
        NOEMA_WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
        NOEMA_GATE = ROOT / "scripts/ci/noema_review_gate.py"
        CODEGRAPH_HELPER = ROOT / "scripts/ci/noema_codegraph_context.sh"


        def test_noema_workflow_materializes_trusted_codegraph_before_review() -> None:
            """The trusted workflow must produce exact-head CodeGraph evidence before model work."""
            workflow = NOEMA_WORKFLOW.read_text(encoding="utf-8")
            materialize = workflow.index("Materialize trusted Noema CodeGraph evidence")
            review = workflow.index("Run Noema LLM review and submit verdict")
            assert materialize < review
            assert "NOEMA_CODEGRAPH_CONTEXT_PATH: ${{ runner.temp }}/noema-codegraph-evidence.md" in workflow
            assert 'NOEMA_REQUIRE_CODEGRAPH_CONTEXT: "1"' in workflow
            assert "scripts/ci/noema_codegraph_context.sh" in workflow


        def test_noema_codegraph_helper_keeps_pr_source_data_only() -> None:
            """CodeGraph may parse exact-head source but must not execute target-owned tooling."""
            helper = CODEGRAPH_HELPER.read_text(encoding="utf-8")
            for required in (
                "CODEGRAPH_NO_DOWNLOAD=1",
                "refs/pull/${PR_NUMBER}/head",
                "EXPECTED_HEAD_SHA",
                "PR_BASE_SHA",
                "unset GH_TOKEN",
                "codegraph-package/package-lock.json",
                "codegraph-package/package.json",
                '"$CODEGRAPH_BIN" init -i',
                '"$CODEGRAPH_BIN" explore',
                "# Trusted CodeGraph current-head evidence",
                "Head SHA:",
            ):
                assert required in helper
            for forbidden in (
                "pytest",
                "npm test",
                "npm run",
                "cargo test",
                "go test",
                "gradle",
                "mvn test",
            ):
                assert forbidden not in helper


        def test_noema_gate_requires_exact_head_bound_codegraph_when_workflow_requests_it() -> None:
            """The model gate must fail closed if required structural evidence is absent or stale."""
            source = NOEMA_GATE.read_text(encoding="utf-8")
            assert "NOEMA_REQUIRE_CODEGRAPH_CONTEXT" in source
            assert "NOEMA_CODEGRAPH_CONTEXT_PATH" in source
            assert "Trusted CodeGraph current-head evidence" in source
            assert "CodeGraph context head does not match the pull request head" in source


        def test_codegraph_loader_accepts_only_the_exact_reviewed_head(monkeypatch, tmp_path: Path) -> None:
            """Exact-head packets are admitted while predecessor packets are rejected."""
            current_head = "a" * 40
            packet = tmp_path / "codegraph.md"
            packet.write_text(
                "# Trusted CodeGraph current-head evidence\\n\\n"
                f"- Head SHA: `{current_head}`\\n\\n"
                "## Changed-scope exploration\\nsource-backed graph evidence\\n",
                encoding="utf-8",
            )
            monkeypatch.setenv("NOEMA_REQUIRE_CODEGRAPH_CONTEXT", "1")
            monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(packet))
            assert "source-backed graph evidence" in gate.load_codegraph_context(current_head)
            with pytest.raises(RuntimeError, match="head does not match"):
                gate.load_codegraph_context("b" * 40)


        def test_codegraph_loader_fails_closed_when_required_packet_is_missing(monkeypatch) -> None:
            """Required structural context cannot silently degrade to changed-file context only."""
            monkeypatch.setenv("NOEMA_REQUIRE_CODEGRAPH_CONTEXT", "1")
            monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
            with pytest.raises(RuntimeError, match="path was not configured"):
                gate.load_codegraph_context("a" * 40)
        '''
    )
    Path("tests/test_noema_codegraph_context_contract.py").write_text(
        codegraph_test, encoding="utf-8"
    )

    replace_once(
        "tests/test_noema_observed_defect_probe_taxonomy.py",
        '    assert "CodeGraph context" not in prompt_text\n',
        '    assert "bounded changed-file context" in prompt_text\n',
    )

    doctoring = "docs/doctoring/noema-observed-defect-probe-taxonomy.md"
    replace_once(
        doctoring,
        "The prompt no longer claims CodeGraph context is supplied: no trusted Noema workflow currently wires that input, so only actual changed-file and review-thread context is advertised. Protected-main deleted-file evidence remains intact: current `main` supplies immutable merge-base lookup and pre-deletion content for removed paths, and the reconciled branch preserves that stronger context boundary.",
        "The trusted Noema workflow now materializes bounded CodeGraph evidence from an exact-head PR-source clone before model execution. The clone is treated strictly as data: the helper executes only the lock-pinned central CodeGraph CLI, removes GitHub credentials before indexing/exploration, forbids target-owned test/build tooling in the helper contract, and writes a current-head marker under `runner.temp`. The Python gate requires that packet when the workflow enables it and fails closed on missing, oversized, non-regular, or stale-head evidence. Protected-main deleted-file evidence remains intact: current `main` supplies immutable merge-base lookup and pre-deletion content for removed paths, and the reconciled branch preserves that stronger context boundary.",
    )
    replace_once(
        doctoring,
        "8. an exercised `call_llm` request contains every supported class and its witness-field schema while making no unwired CodeGraph claim; and\n"
        "9. every requirements file installed by the permanent observed-probe workflow is included in that workflow's `pull_request.paths`, so lockfile-only environment changes cannot bypass the focused contracts.",
        "8. an exercised `call_llm` request contains every supported class and its witness-field schema while preserving the supplied bounded evidence;\n"
        "9. trusted CodeGraph evidence is generated before review, exact-head bound, required by the gate, and produced without executing target-owned test/build commands; and\n"
        "10. every requirements file installed by the permanent observed-probe workflow is included in that workflow's `pull_request.paths`, so lockfile-only environment changes cannot bypass the focused contracts.",
    )

    baseline = "docs/product-technical-gap-baseline.md"
    replace_once(
        baseline,
        "The same repair removes the stale claim that CodeGraph context is supplied to Noema: the trusted workflow does not wire `NOEMA_CODEGRAPH_CONTEXT_PATH`, so the prompt now advertises only changed-file and review-thread context actually provided. This strengthens review evidence without claiming parity or superiority over proprietary reviewers; the corpus is grounded only in concrete, independently observed PR findings.",
        "The same review-quality lane now wires bounded CodeGraph evidence into Noema instead of merely claiming structural context: a trusted helper fetches the exact PR head and base, drops GitHub credentials before running the lock-pinned central CodeGraph CLI, records the reviewed head in the evidence packet, and the gate fails closed if the required packet is missing or stale. Changed-file and review-thread evidence remain available beside that structural context. This strengthens cross-file/dependency reasoning without claiming parity or superiority over proprietary reviewers; the corpus remains grounded only in concrete, independently observed PR findings.",
    )

    changelog = Path("CHANGELOG.md")
    changelog_text = changelog.read_text(encoding="utf-8")
    marker = "## [Unreleased]\n"
    if marker not in changelog_text:
        raise SystemExit("CHANGELOG Unreleased marker missing")
    entry = (
        "- **Bind Noema to trusted exact-head CodeGraph evidence (`#1589`).** "
        "The required reviewer now materializes the PR source as data, removes GitHub credentials before lock-pinned CodeGraph indexing/exploration, passes a bounded head-marked structural evidence packet to the reviewer, and fails closed if required evidence is missing or stale. Target-owned test/build commands remain outside this trusted path.\n"
    )
    if entry not in changelog_text:
        changelog.write_text(changelog_text.replace(marker, marker + entry, 1), encoding="utf-8")

    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    gate = Path(gate_path).read_text(encoding="utf-8")
    helper_text = Path("scripts/ci/noema_codegraph_context.sh").read_text(encoding="utf-8")
    for token in (
        "Materialize trusted Noema CodeGraph evidence",
        'NOEMA_REQUIRE_CODEGRAPH_CONTEXT: "1"',
        "NOEMA_CODEGRAPH_CONTEXT_PATH: ${{ runner.temp }}/noema-codegraph-evidence.md",
    ):
        if token not in workflow:
            raise SystemExit(f"workflow invariant missing: {token}")
    for token in (
        "NOEMA_REQUIRE_CODEGRAPH_CONTEXT",
        "NOEMA_CODEGRAPH_CONTEXT_PATH",
        "Trusted CodeGraph current-head evidence",
        "CodeGraph context head does not match the pull request head",
    ):
        if token not in gate:
            raise SystemExit(f"gate invariant missing: {token}")
    for token in (
        "CODEGRAPH_NO_DOWNLOAD=1",
        "refs/pull/${PR_NUMBER}/head",
        '"$CODEGRAPH_BIN" init -i',
        '"$CODEGRAPH_BIN" explore',
        "unset GH_TOKEN",
    ):
        if token not in helper_text:
            raise SystemExit(f"helper invariant missing: {token}")

    # The temporary workflow and this transformer must disappear in the GREEN commit.
    Path(".github/workflows/source-fix-1589-noema-codegraph.yml").unlink()
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
