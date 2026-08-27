#!/usr/bin/env python3
"""Apply the bounded read-only OpenCode gateway migration."""

from pathlib import Path
import re

path = Path(".github/workflows/opencode-review-dispatch.yml")
text = path.read_text(encoding="utf-8")

pool_marker = "      - name: Run OpenCode PR Review model pool\n"
if text.count(pool_marker) != 1:
    raise SystemExit("expected exactly one read-only model pool step")

sidecar_step = """      - name: Provision contextual-orchestrator read-only review gateway
        if: needs.coverage-evidence.result == 'success'
        env:
          BYTEZ_API_KEY: ${{ secrets.BYTEZ_API_KEY }}
          NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
          NVIDIA_NIM_API_KEY_SUB: ${{ secrets.NVIDIA_NIM_API_KEY_SUB }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          set -euo pipefail
          bash "$GITHUB_WORKSPACE/scripts/ci/contextual_orchestrator_review_sidecar.sh"

"""
text = text.replace(pool_marker, sidecar_step + pool_marker, 1)

old_assertion = """          if ! grep -Fq 'nvidia-nim' "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc" \\
            || ! grep -Fq 'integrate.api.nvidia.com' "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc"; then
            echo '::error::Generated isolated opencode.jsonc is missing the nvidia-nim provider; refusing to run the model pool without NIM priority.'
            exit 1
          fi
          printf 'Prepared isolated OpenCode review workspace: %s\\n' "$OPENCODE_REVIEW_WORKDIR"
"""
if text.count(old_assertion) != 1:
    raise SystemExit("could not find the direct-provider config assertion")

gateway_assertion = """          python3 - "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc" <<'PY'
          import json
          from pathlib import Path
          import sys

          config_path = Path(sys.argv[1])
          config = json.loads(config_path.read_text(encoding="utf-8"))
          gateway_provider = {
              "npm": "@ai-sdk/openai-compatible",
              "name": "Contextual Orchestrator",
              "options": {
                  "baseURL": "{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}",
                  "apiKey": "{env:CONTEXTUAL_ORCHESTRATOR_TOKEN}",
              },
              "models": {
                  "orchestrator/free": {
                      "name": "Orchestrator Free (ZDR-first zero-cost pool)",
                      "tool_call": True,
                      "reasoning": True,
                      "options": {"reasoningEffort": "high"},
                      "variants": {
                          "high": {"reasoningEffort": "high"},
                      },
                      "limit": {"context": 200000, "output": 32768},
                  }
              },
          }
          config["model"] = "contextual-orchestrator/orchestrator/free"
          config["small_model"] = "contextual-orchestrator/orchestrator/free"
          config["enabled_providers"] = ["contextual-orchestrator"]
          config["provider"] = {"contextual-orchestrator": gateway_provider}
          config_path.write_text(
              json.dumps(config, indent=2, sort_keys=True) + "\\n",
              encoding="utf-8",
          )
          PY
          if grep -Eq 'integrate\\.api\\.nvidia\\.com|models\\.github\\.ai|api\\.openai\\.com|openrouter\\.ai|opencode\\.ai/zen' "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc"; then
            echo '::error::Generated isolated opencode.jsonc still contains a direct-provider route.'
            exit 1
          fi
          if ! grep -Fq 'contextual-orchestrator' "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc" \\
            || ! grep -Fq 'orchestrator/free' "${OPENCODE_REVIEW_WORKDIR}/opencode.jsonc"; then
            echo '::error::Generated isolated opencode.jsonc is missing the contextual-orchestrator gateway.'
            exit 1
          fi
          printf 'Prepared isolated OpenCode review workspace: %s\\n' "$OPENCODE_REVIEW_WORKDIR"
"""
text = text.replace(old_assertion, gateway_assertion, 1)

env_pattern = re.compile(
    r"        env:\n"
    r"          STRIX_GITHUB_MODELS_TOKEN:.*?"
    r'          OPENCODE_MODEL_ATTEMPTS: "1"\n',
    re.DOTALL,
)
gateway_env = """        env:
          SHARE: "false"
          NPM_CONFIG_IGNORE_SCRIPTS: "true"
          NO_COLOR: "1"
          # Provider discovery, ZDR prioritization, and fallback live inside
          # contextual-orchestrator. The read-only process inherits only the
          # sidecar URL/token from GITHUB_ENV and the virtual zero-cost model.
          OPENCODE_MODEL_CANDIDATES: "contextual-orchestrator/orchestrator/free"
          OPENCODE_MODEL_ATTEMPTS: "1"
"""
text, count = env_pattern.subn(gateway_env, text, count=1)
if count != 1:
    raise SystemExit("could not replace the direct-provider model-pool environment")

provider_budget_pattern = re.compile(
    r'          OPENCODE_NVIDIA_NIM_RUN_TIMEOUT_SECONDS: "180"\n'
    r".*?"
    r'          OPENCODE_GITHUB_GPT5_RUN_TIMEOUT_SECONDS: "45"\n',
    re.DOTALL,
)
text, count = provider_budget_pattern.subn(
    "          # Provider-specific fallback and timeout policy is owned by the gateway.\n",
    text,
    count=1,
)
if count != 1:
    raise SystemExit("could not remove direct-provider timeout policy")

path.write_text(text, encoding="utf-8")
