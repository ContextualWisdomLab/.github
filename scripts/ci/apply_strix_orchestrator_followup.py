#!/usr/bin/env python3
"""Apply and verify the one-shot Strix contextual-orchestrator follow-up."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/strix.yml"
SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
SMOKE = ROOT / "scripts/ci/strix_required_workflow_smoke.sh"
CHANGELOG = ROOT / "CHANGELOG.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
TEST_FILE = ROOT / "tests/test_strix_contextual_orchestrator_contract.py"
BOOTSTRAP_WORKFLOW = ROOT / ".github/workflows/apply-strix-orchestrator-followup.yml"
BOOTSTRAP_SCRIPT = ROOT / "scripts/ci/apply_strix_orchestrator_followup.py"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a repository command with text output."""

    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        text=True,
        stdout=None,
        stderr=None,
    )


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace exactly one tracked fragment or fail without ambiguity."""

    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: expected one replacement anchor, found {count}: {old[:120]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_once(path: Path, pattern: str, replacement: str) -> None:
    """Replace exactly one regular-expression match."""

    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _: replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: expected one regex match, found {count}: {pattern!r}"
        )
    path.write_text(updated, encoding="utf-8")


def write_red_contract() -> None:
    """Write the desired workflow contract before changing production files."""

    TEST_FILE.write_text(
        textwrap.dedent(
            '''\
            """Contracts for routing default Strix scans through contextual-orchestrator."""

            from __future__ import annotations

            from pathlib import Path
            import unittest

            ROOT = Path(__file__).resolve().parents[1]
            WORKFLOW = ROOT / ".github/workflows/strix.yml"
            SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
            SMOKE = ROOT / "scripts/ci/strix_required_workflow_smoke.sh"


            class StrixContextualOrchestratorContract(unittest.TestCase):
                """Pin the gateway-first default while retaining explicit diagnostics."""

                def setUp(self) -> None:
                    """Load the tracked workflow and helper contracts."""
                    self.workflow = WORKFLOW.read_text(encoding="utf-8")
                    self.sidecar = SIDECAR.read_text(encoding="utf-8")
                    self.smoke = SMOKE.read_text(encoding="utf-8")

                def test_default_scan_provisions_the_existing_gateway_sidecar(self) -> None:
                    """Normal scans use the five-provider gateway, not a direct pool."""
                    self.assertIn("Provision contextual-orchestrator Strix sidecar", self.workflow)
                    self.assertIn(
                        "STRIX_MODEL: ${{ github.event.client_payload.strix_llm || 'contextual-orchestrator/orchestrator/free' }}",
                        self.workflow,
                    )
                    self.assertIn("provider_mode=contextual_orchestrator", self.workflow)
                    self.assertNotIn(
                        "steps.resolve_nvidia_models.outputs.primary || 'gpt-5.4'",
                        self.workflow,
                    )

                def test_gateway_is_openai_compatible_and_loopback_bound(self) -> None:
                    """Strix calls the local OpenAI-compatible route with a bearer token."""
                    self.assertIn("openai/orchestrator/free", self.workflow)
                    self.assertIn("CONTEXTUAL_ORCHESTRATOR_BASE_URL", self.workflow)
                    self.assertIn("CONTEXTUAL_ORCHESTRATOR_TOKEN", self.workflow)
                    self.assertIn("^http://127\\.0\\.0\\.1:[0-9]{1,5}$", self.workflow)
                    self.assertIn("${CONTEXTUAL_ORCHESTRATOR_BASE_URL}/v1", self.workflow)

                def test_explicit_direct_provider_diagnostics_remain_available(self) -> None:
                    """A caller-selected diagnostic model preserves existing direct modes."""
                    self.assertIn("github.event.client_payload.strix_llm", self.workflow)
                    self.assertIn("nvidia_nim/*)", self.workflow)
                    self.assertIn("openrouter/free", self.workflow)
                    self.assertIn("openai-direct/gpt-5.4", self.workflow)

                def test_gateway_install_is_isolated_and_token_is_masked(self) -> None:
                    """The sidecar cannot overwrite Strix's hash-locked Python runtime."""
                    self.assertIn('--target "$ORCHESTRATOR_SITE_PACKAGES"', self.sidecar)
                    self.assertIn(
                        'PYTHONPATH="$ORCHESTRATOR_SITE_PACKAGES:$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT"',
                        self.sidecar,
                    )
                    self.assertIn("::add-mask::%s", self.sidecar)

                def test_required_smoke_pins_the_gateway_default(self) -> None:
                    """The bounded smoke rejects a future direct-default regression."""
                    self.assertIn("contextual-orchestrator Strix sidecar", self.smoke)
                    self.assertIn("openai/orchestrator/free", self.smoke)
                    self.assertIn("direct-provider models only as explicit diagnostics", self.smoke)


            if __name__ == "__main__":
                unittest.main()
            '''
        ),
        encoding="utf-8",
    )


def verify_red() -> None:
    """Prove the desired contract fails against the predecessor implementation."""

    result = run("python3", str(TEST_FILE.relative_to(ROOT)), check=False)
    if result.returncode == 0:
        raise SystemExit(
            "RED contract unexpectedly passed before the Strix gateway implementation"
        )
    print("RED confirmed: predecessor direct-provider default violates the gateway contract.")


def apply_production_changes() -> None:
    """Apply the minimal gateway-first production and documentation changes."""

    replace_once(
        WORKFLOW,
        """      - name: Resolve live NVIDIA NIM Strix models
        id: resolve_nvidia_models
""",
        """      - name: Provision contextual-orchestrator Strix sidecar
        if: github.event_name != 'repository_dispatch' || github.event.client_payload.strix_llm == ''
        env:
          BYTEZ_API_KEY: ${{ secrets.BYTEZ_API_KEY }}
          NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
          NVIDIA_NIM_API_KEY_SUB: ${{ secrets.NVIDIA_NIM_API_KEY_SUB }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          set -euo pipefail
          bash "$TRUSTED_STRIX_SOURCE/scripts/ci/contextual_orchestrator_review_sidecar.sh"

      - name: Resolve live NVIDIA NIM Strix models
        id: resolve_nvidia_models
""",
    )
    replace_once(
        WORKFLOW,
        """          if [ -n "$STRIX_MODEL_REQUESTED" ] || [ "$TARGET_REPOSITORY_PRIVATE" != "false" ] || [ -z "${NVIDIA_API_KEY:-}" ]; then
""",
        """          if [ -z "$STRIX_MODEL_REQUESTED" ] || [ "$TARGET_REPOSITORY_PRIVATE" != "false" ] || [ -z "${NVIDIA_API_KEY:-}" ]; then
""",
    )
    replace_once(
        WORKFLOW,
        """          STRIX_MODEL: ${{ github.event.client_payload.strix_llm || (steps.target_visibility.outputs.is_private == 'false' && steps.resolve_nvidia_models.outputs.primary || 'gpt-5.4') }}
""",
        """          STRIX_MODEL: ${{ github.event.client_payload.strix_llm || 'contextual-orchestrator/orchestrator/free' }}
""",
    )
    replace_once(
        WORKFLOW,
        """          STRIX_GITHUB_MODELS_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}
          TARGET_REPOSITORY_PRIVATE: ${{ steps.target_visibility.outputs.is_private }}
""",
        """          STRIX_GITHUB_MODELS_TOKEN: ${{ secrets.STRIX_GITHUB_MODELS_TOKEN || github.token }}
          CONTEXTUAL_ORCHESTRATOR_BASE_URL: ${{ env.CONTEXTUAL_ORCHESTRATOR_BASE_URL }}
          CONTEXTUAL_ORCHESTRATOR_TOKEN: ${{ env.CONTEXTUAL_ORCHESTRATOR_TOKEN }}
          TARGET_REPOSITORY_PRIVATE: ${{ steps.target_visibility.outputs.is_private }}
""",
    )
    replace_once(
        WORKFLOW,
        """          echo "strix_model=$strix_model" >> "$GITHUB_OUTPUT"
          case "$strix_model" in
""",
        """          echo "strix_model=$strix_model" >> "$GITHUB_OUTPUT"
          case "$strix_model" in
            contextual-orchestrator/orchestrator/free)
              echo 'enabled=true' >> "$GITHUB_OUTPUT"
              echo 'provider_mode=contextual_orchestrator' >> "$GITHUB_OUTPUT"
              if ! [[ "$CONTEXTUAL_ORCHESTRATOR_BASE_URL" =~ ^http://127\\.0\\.0\\.1:[0-9]{1,5}$ ]]; then
                echo '::error::The contextual-orchestrator Strix sidecar must use an exact IPv4 loopback URL and explicit port.'
                exit 1
              fi
              sidecar_port="${CONTEXTUAL_ORCHESTRATOR_BASE_URL##*:}"
              if [ "$sidecar_port" -lt 1 ] || [ "$sidecar_port" -gt 65535 ]; then
                echo '::error::The contextual-orchestrator Strix sidecar port must be between 1 and 65535.'
                exit 1
              fi
              sanitized_orchestrator_token="$(printf '%s' "$CONTEXTUAL_ORCHESTRATOR_TOKEN" | tr -d '\\r\\n')"
              trimmed_orchestrator_token="$(printf '%s' "$sanitized_orchestrator_token" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
              if [ -z "$trimmed_orchestrator_token" ] || [ "$trimmed_orchestrator_token" != "$CONTEXTUAL_ORCHESTRATOR_TOKEN" ]; then
                echo '::error::The contextual-orchestrator Strix sidecar requires one non-empty, line-safe bearer token.'
                exit 1
              fi
              ;;
""",
    )
    replace_once(
        WORKFLOW,
        """              echo '::error::STRIX_LLM must select NVIDIA NIM Nemotron, GitHub Models openai/gpt-5 or newer, direct OpenAI GPT-5.4 or newer, OpenRouter openrouter/free, or an approved organization Vertex AI model.'
""",
        """              echo '::error::STRIX_LLM must select contextual-orchestrator/orchestrator/free, NVIDIA NIM Nemotron, GitHub Models openai/gpt-5 or newer, direct OpenAI GPT-5.4 or newer, OpenRouter openrouter/free, or an approved organization Vertex AI model.'
""",
    )
    regex_once(
        WORKFLOW,
        r"^          LLM_API_KEY: \$\{\{.*\}\}$",
        "          LLM_API_KEY: ${{ steps.gate.outputs.provider_mode == 'contextual_orchestrator' && env.CONTEXTUAL_ORCHESTRATOR_TOKEN || steps.gate.outputs.provider_mode == 'github_models' && (secrets.STRIX_GITHUB_MODELS_TOKEN || github.token) || steps.gate.outputs.provider_mode == 'openai_direct' && (secrets.STRIX_OPENAI_API_KEY || secrets.OPENAI_API_KEY) || steps.gate.outputs.provider_mode == 'openrouter' && secrets.OPENROUTER_API_KEY || steps.gate.outputs.provider_mode == 'nvidia_nim' && secrets.NVIDIA_NIM_API_KEY || '' }}",
    )
    regex_once(
        WORKFLOW,
        r"^          LLM_API_KEY_SECRET: \$\{\{.*\}\}$",
        "          LLM_API_KEY_SECRET: ${{ steps.gate.outputs.provider_mode == 'contextual_orchestrator' && env.CONTEXTUAL_ORCHESTRATOR_TOKEN || steps.gate.outputs.provider_mode == 'github_models' && (secrets.STRIX_GITHUB_MODELS_TOKEN || github.token) || steps.gate.outputs.provider_mode == 'openai_direct' && (secrets.STRIX_OPENAI_API_KEY || secrets.OPENAI_API_KEY) || steps.gate.outputs.provider_mode == 'openrouter' && secrets.OPENROUTER_API_KEY || steps.gate.outputs.provider_mode == 'nvidia_nim' && secrets.NVIDIA_NIM_API_KEY || '' }}",
    )
    replace_once(
        WORKFLOW,
        """          if [ -z "$trimmed" ] && [ "$PROVIDER_MODE" = "github_models" ]; then
""",
        """          if [ -z "$trimmed" ] && [ "$PROVIDER_MODE" = "contextual_orchestrator" ]; then
            echo '::error::CONTEXTUAL_ORCHESTRATOR_TOKEN is required for gateway-backed Strix scans.'
            exit 1
          fi
          if [ -z "$trimmed" ] && [ "$PROVIDER_MODE" = "github_models" ]; then
""",
    )
    replace_once(
        WORKFLOW,
        """      - name: Prepare OpenRouter API base
""",
        """      - name: Prepare contextual-orchestrator API base
        if: steps.gate.outputs.provider_mode == 'contextual_orchestrator'
        env:
          CONTEXTUAL_ORCHESTRATOR_BASE_URL: ${{ env.CONTEXTUAL_ORCHESTRATOR_BASE_URL }}
        run: |
          set -euo pipefail
          if ! [[ "$CONTEXTUAL_ORCHESTRATOR_BASE_URL" =~ ^http://127\\.0\\.0\\.1:[0-9]{1,5}$ ]]; then
            echo '::error::The contextual-orchestrator API base must remain on exact IPv4 loopback.'
            exit 1
          fi
          umask 077
          llm_api_base_file="$RUNNER_TEMP/llm_api_base.txt"
          printf '%s' "${CONTEXTUAL_ORCHESTRATOR_BASE_URL}/v1" > "$llm_api_base_file"
          echo "LLM_API_BASE_FILE=$llm_api_base_file" >> "$GITHUB_ENV"

      - name: Prepare OpenRouter API base
""",
    )
    replace_once(
        WORKFLOW,
        """          strix_llm_file="$RUNNER_TEMP/strix_llm.txt"
          strix_model="$(printf '%s' "$STRIX_MODEL" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
          case "$strix_model" in
""",
        """          strix_llm_file="$RUNNER_TEMP/strix_llm.txt"
          strix_model="$(printf '%s' "$STRIX_MODEL" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
          case "$strix_model" in
            contextual-orchestrator/orchestrator/free)
              printf '%s' 'openai/orchestrator/free' > "$strix_llm_file"
              ;;
""",
    )

    replace_once(
        SIDECAR,
        """ORCHESTRATOR_WORK="${RUNNER_TEMP:-/tmp}/contextual-orchestrator-review"
""",
        """ORCHESTRATOR_WORK="${RUNNER_TEMP:-/tmp}/contextual-orchestrator-review"
ORCHESTRATOR_SITE_PACKAGES="$ORCHESTRATOR_WORK/site-packages"
""",
    )
    replace_once(
        SIDECAR,
        """ORCHESTRATOR_TOKEN="${ORCHESTRATOR_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"

mkdir -p "$ORCHESTRATOR_WORK"
rm -rf "$ORCHESTRATOR_SOURCE"
""",
        """ORCHESTRATOR_TOKEN="${ORCHESTRATOR_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
case "$ORCHESTRATOR_TOKEN" in
  *$'\\r'*|*$'\\n'*) fail "ORCHESTRATOR_TOKEN must not contain carriage returns or newlines" ;;
esac

mkdir -p "$ORCHESTRATOR_WORK"
rm -rf "$ORCHESTRATOR_SOURCE" "$ORCHESTRATOR_SITE_PACKAGES"
mkdir -p "$ORCHESTRATOR_SITE_PACKAGES"
""",
    )
    replace_once(
        SIDECAR,
        """python3 -m pip install --quiet --disable-pip-version-check --no-cache-dir "$ORCHESTRATOR_SOURCE"
""",
        """python3 -m pip install --quiet --disable-pip-version-check --no-cache-dir --target "$ORCHESTRATOR_SITE_PACKAGES" "$ORCHESTRATOR_SOURCE"
""",
    )
    replace_once(
        SIDECAR,
        """PYTHONPATH="$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT" \\
""",
        """PYTHONPATH="$ORCHESTRATOR_SITE_PACKAGES:$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT" \\
""",
    )
    replace_once(
        SIDECAR,
        """if [ -n "$ORCHESTRATOR_GITHUB_ENV" ]; then
  {
""",
        """printf '::add-mask::%s\\n' "$ORCHESTRATOR_TOKEN"
if [ -n "$ORCHESTRATOR_GITHUB_ENV" ]; then
  {
""",
    )

    replace_once(
        SMOKE,
        """full_gate_test="$repo_root/scripts/ci/test_strix_quick_gate.sh"
""",
        """full_gate_test="$repo_root/scripts/ci/test_strix_quick_gate.sh"
sidecar_script="$repo_root/scripts/ci/contextual_orchestrator_review_sidecar.sh"
""",
    )
    replace_once(
        SMOKE,
        """if ! bash -n "$gate_script" "$full_gate_test"; then
""",
        """if ! bash -n "$gate_script" "$full_gate_test" "$sidecar_script"; then
""",
    )
    replace_once(
        SMOKE,
        """assert_file_contains "$workflow_file" "nvidia/nemotron-3-super-120b-a12b" "Strix defaults public scans to the current hosted NVIDIA NIM model"
""",
        """assert_file_contains "$workflow_file" "Provision contextual-orchestrator Strix sidecar" "Strix defaults normal scans to the contextual-orchestrator Strix sidecar"
assert_file_contains "$workflow_file" "contextual-orchestrator/orchestrator/free" "Strix selects the fail-closed orchestrator/free gateway pool by default"
assert_file_contains "$workflow_file" "openai/orchestrator/free" "Strix addresses the gateway through its OpenAI-compatible model namespace"
assert_file_contains "$workflow_file" "CONTEXTUAL_ORCHESTRATOR_BASE_URL" "Strix consumes the loopback gateway base URL"
assert_file_contains "$workflow_file" "CONTEXTUAL_ORCHESTRATOR_TOKEN" "Strix consumes the generated gateway bearer token"
assert_file_contains "$sidecar_script" '--target "$ORCHESTRATOR_SITE_PACKAGES"' "Strix sidecar dependencies are isolated from the hash-locked scanner runtime"
assert_file_contains "$sidecar_script" "::add-mask::%s" "Strix sidecar masks its generated bearer token"
assert_file_contains "$workflow_file" "nvidia/nemotron-3-super-120b-a12b" "Strix retains direct-provider models only as explicit diagnostics"
""",
    )

    replace_once(
        CHANGELOG,
        """## [Unreleased]
""",
        """## [Unreleased]
- Required Strix security evidence now uses the existing vendored
  `contextual-orchestrator` sidecar and its fail-closed `orchestrator/free`
  ZDR-first zero-cost pool for normal scans. Direct NVIDIA NIM, OpenRouter,
  GitHub Models, OpenAI, and Vertex paths remain available only when an
  authorized `repository_dispatch` explicitly supplies `strix_llm` for
  diagnosis. Gateway startup, loopback binding, bearer-token masking, and an
  isolated `--target` dependency tree fail closed; Strix receives only the
  loopback OpenAI-compatible token/base while provider credentials stay inside
  the sidecar process. The gateway route owns provider/model failover, so the
  scanner does not append a second direct-provider fallback chain.
""",
    )
    replace_once(
        BASELINE,
        """## 1. 근거와 범위
""",
        """## 2026-08-28 live delta — Strix provider authority

- DiskSage #264의 exact-head 제품·Release·SAST·Security 검증은 성공했지만,
  중앙 Strix는 NVIDIA 429, NVIDIA fallback 404, OpenRouter 502, OpenAI
  `insufficient_quota`가 연속 발생해 권위 있는 취약점 보고서를 만들지 못하고
  `STRIX_PROVIDER_UNAVAILABLE`로 fail-closed 종료했다. 이 결과를 제품 결함이나
  성공 증거로 오인하지 않는다.
- 정상 Strix 실행의 provider/model 선택 권한은 vendored
  `contextual-orchestrator`의 `orchestrator/free` ZDR-first pool로 이동한다.
  명시적 `repository_dispatch.strix_llm`만 기존 direct-provider 진단 경로를
  선택할 수 있다. Gateway 실패는 direct fallback으로 위장하지 않고 required
  Check를 실패시킨다.
- 소비 저장소 PR은 중앙 provider outage를 고치기 위한 no-op commit이나 반복
  rerun을 만들지 않는다. 중앙 수정이 병합된 뒤 unchanged exact head에 새 Strix
  evidence를 dispatch하고, 독립 승인과 모든 required Check를 다시 요구한다.

## 1. 근거와 범위
""",
    )

    (ROOT / "docs/adr/0004-strix-contextual-orchestrator-authority.md").write_text(
        """# ADR-0004: contextual-orchestrator owns normal Strix provider routing

- Status: Proposed
- Date: 2026-08-28
- Owners: ContextualWisdomLab central CI maintainers
- Figma File ID: N/A (workflow/control-plane change; no customer UI)

## Context

Required Strix scans were serialized per repository, but each scan still owned a
hard-coded direct provider chain. A live DiskSage exact-head scan exhausted four
independent paths in one run: NVIDIA rate limiting, an unavailable NVIDIA model,
an OpenRouter upstream error, and exhausted direct OpenAI credit. No authoritative
vulnerability report existed, so the required check correctly failed closed, but
consumer product PRs could not repair the shared authority boundary.

The central repository already vendors a pinned contextual-orchestrator sidecar.
It registers the five organization provider credentials in a process-local KV,
performs live discovery, applies the reviewed zero-cost/ZDR policy, and exposes
`orchestrator/free` through an authenticated OpenAI-compatible loopback API.

## Decision

Normal Strix scans SHALL provision that sidecar and call
`openai/orchestrator/free` through exact IPv4 loopback. The sidecar owns
provider/model discovery and fallback. Strix SHALL NOT add a second direct
fallback chain for the gateway-backed route.

A caller MAY use `repository_dispatch.strix_llm` to select an existing direct
provider model for bounded diagnosis. That override is explicit, auditable, and
does not change the normal default.

The sidecar dependency tree SHALL be installed into an isolated `--target`
directory so it cannot rewrite the hash-locked Strix runtime. Its generated
bearer token SHALL be line-safe, masked before export, and passed to Strix only
through a mode-specific file. Missing credentials, unhealthy startup, non-loopback
base URLs, invalid ports, and missing tokens fail closed.

## Consequences

- Shared provider outages are handled by one routing authority instead of nested
  retry/fallback loops.
- Provider credentials remain inside the gateway process; the scanner sees only
  a short-lived loopback credential.
- A gateway outage remains non-passing security evidence.
- Existing direct-provider diagnostic contracts and their tests remain supported.
- After merge, consumer PRs require a fresh exact-head Strix run; predecessor
  outage evidence is not transferred.

## Verification

- RED/GREEN static contract for the workflow, model namespace, loopback and token.
- Bounded required-workflow smoke contract.
- Bash syntax and YAML parse.
- Existing full organization Checks, independent review, and protected merge.

## Rollback

Revert this ADR and its workflow commit. Do not partially restore a direct default
while leaving gateway key/base files active. Re-run the complete required Strix
contract and affected consumer exact heads after rollback.
""",
        encoding="utf-8",
    )
    (ROOT / "docs/doctoring/strix-contextual-orchestrator-gateway.md").write_text(
        """# Strix contextual-orchestrator gateway doctoring

## Failure evidence

The triggering consumer scan produced no vulnerability artifact. Its terminal
log recorded provider infrastructure failures across NVIDIA NIM, OpenRouter, and
direct OpenAI, followed by the existing fail-closed
`STRIX_PROVIDER_UNAVAILABLE` classification. Repository Test, Release, SAST, and
Security workflows were independently successful on the same consumer head.

## Causal boundary

The defect is not in the consumer product tree. It is the duplicated routing
authority in central Strix: the scanner selected and retried direct providers even
though the organization already had a pinned contextual-orchestrator gateway with
model discovery, ZDR policy, and provider-family diversity.

## Corrective control

```text
five provider credentials
→ process-local contextual-orchestrator KV
→ live discovery + ZDR-first zero-cost catalog
→ authenticated 127.0.0.1 OpenAI-compatible API
→ Strix openai/orchestrator/free
→ authoritative report or fail-closed required check
```

Direct providers are retained only for an explicit diagnostic override. The
normal gateway route has no scanner-owned fallback list.

## Security and operability

- The sidecar is pinned by commit SHA.
- Provider credentials never become Strix key files in gateway mode.
- The bearer token is generated per job, rejects line breaks, and is masked.
- The base URL must be exact IPv4 loopback with a valid port.
- Sidecar packages use an isolated target directory rather than the scanner's
  hash-locked environment.
- Health failure, empty discovery, missing credentials, and provider exhaustion
  remain non-passing.
- Consumer PRs are rechecked on unchanged exact heads after the central fix.

## Traceability

- ADR: `docs/adr/0004-strix-contextual-orchestrator-authority.md`
- Workflow: `.github/workflows/strix.yml`
- Sidecar: `scripts/ci/contextual_orchestrator_review_sidecar.sh`
- Required smoke: `scripts/ci/strix_required_workflow_smoke.sh`
- Contract: `tests/test_strix_contextual_orchestrator_contract.py`
- Predecessor gateway ADR: `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
""",
        encoding="utf-8",
    )


def verify_green() -> None:
    """Run focused exact-tree verification before creating the final commit."""

    run("python3", str(TEST_FILE.relative_to(ROOT)))
    run("bash", "scripts/ci/strix_required_workflow_smoke.sh")
    run("bash", "-n", "scripts/ci/contextual_orchestrator_review_sidecar.sh")
    run("python3", "-m", "compileall", "-q", str(TEST_FILE.relative_to(ROOT)))
    run("ruby", "-e", 'require "yaml"; YAML.load_file(ARGV[0])', ".github/workflows/strix.yml")
    run("git", "diff", "--check")


def commit_verified_patch() -> None:
    """Delete bootstrap-only files and push the verified branch commit."""

    BOOTSTRAP_WORKFLOW.unlink()
    BOOTSTRAP_SCRIPT.unlink()
    run("git", "config", "user.name", "ContextualWisdomLab Automation")
    run("git", "config", "user.email", "automation@contextualwisdomlab.invalid")
    run("git", "add", "-A")
    run("git", "commit", "-m", "fix(strix): route default scans through contextual-orchestrator")
    run("git", "push", "origin", "HEAD:feat/strix-orchestrator-free-zdr")


def main() -> None:
    """Execute RED, GREEN, focused verification, and a self-cleaning commit."""

    write_red_contract()
    verify_red()
    apply_production_changes()
    verify_green()
    commit_verified_patch()


if __name__ == "__main__":
    main()
