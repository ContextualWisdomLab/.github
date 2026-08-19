from pathlib import Path
import re

workflow_path = Path('.github/workflows/strix.yml')
gate_path = Path('scripts/ci/strix_quick_gate.sh')
changelog_path = Path('CHANGELOG.md')
gateway_test_path = Path('tests/test_strix_contextual_gateway.py')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one target, found {count}')
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )
    if count != 1:
        raise SystemExit(f'{label}: expected one regex target, found {count}')
    return updated


gate = gate_path.read_text(encoding='utf-8')
gate_replacement = """has_strix_report_failure_signal() {
\tlocal classifier="$SCRIPT_DIR/strix_report_signal.py"
\tif [ ! -f "$classifier" ] || [ -L "$classifier" ]; then
\t\techo "ERROR: trusted Strix report classifier is unavailable; failing closed." >&2
\t\treturn 0
\tfi
\tif python3 "$classifier" "$@"; then
\t\treturn 0
\telse
\t\tlocal classifier_rc=$?
\t\tcase "$classifier_rc" in
\t\t1)
\t\t\treturn 1
\t\t\t;;
\t\t*)
\t\t\techo "ERROR: Strix report classifier failed; failing closed." >&2
\t\t\treturn 0
\t\t\t;;
\t\tesac
\tfi
}

# shellcheck disable=SC2317,SC2329"""
gate = regex_once(
    gate,
    r'has_strix_report_failure_signal\(\) \{\n.*?\n\}\n\n# shellcheck disable=SC2317,SC2329',
    gate_replacement,
    'replace report signal classifier',
)
gate_path.write_text(gate, encoding='utf-8')

expression_open = '$' + '{{'
gateway_steps = r'''
      - name: Fetch pinned Contextual-Orchestrator source
        id: contextual_source
        if: >-
          steps.gate.outputs.enabled == 'true'
          && !(github.event_name == 'repository_dispatch'
          && github.event.client_payload.strix_llm != '')
        env:
          CONTEXTUAL_ORCHESTRATOR_SHA: 16a2448ab109feceb9113eb0c990c7c51a83a04a
        run: |
          set -euo pipefail
          source_root="$RUNNER_TEMP/contextual-orchestrator-source"
          rm -rf -- "$source_root"
          git init -q "$source_root"
          git -C "$source_root" remote add origin https://github.com/ContextualWisdomLab/contextual-orchestrator.git
          git -C "$source_root" fetch --no-tags --depth=1 origin "$CONTEXTUAL_ORCHESTRATOR_SHA"
          git -C "$source_root" checkout --detach --quiet "$CONTEXTUAL_ORCHESTRATOR_SHA"
          observed_sha="$(git -C "$source_root" rev-parse HEAD)"
          if [ "$observed_sha" != "$CONTEXTUAL_ORCHESTRATOR_SHA" ]; then
            echo "::error::Pinned Contextual-Orchestrator checkout resolved to $observed_sha, expected $CONTEXTUAL_ORCHESTRATOR_SHA."
            exit 1
          fi
          test -f "$source_root/contextual_orchestrator/passthrough_failover.py"
          test -f "$source_root/contextual_orchestrator/model_discovery.py"
          echo "source_root=$source_root" >> "$GITHUB_OUTPUT"

      - name: Prepare Contextual-Orchestrator provider credential manifest
        id: contextual_credentials
        if: >-
          steps.gate.outputs.enabled == 'true'
          && !(github.event_name == 'repository_dispatch'
          && github.event.client_payload.strix_llm != '')
        env:
          NVIDIA_NIM_API_KEY_VALUE: __EXPR__ secrets.NVIDIA_NIM_API_KEY }}
          NVIDIA_NIM_API_KEY_SUB_VALUE: __EXPR__ secrets.NVIDIA_NIM_API_KEY_SUB }}
          BYTEZ_API_KEY_VALUE: __EXPR__ secrets.BYTEZ_API_KEY }}
          OPENROUTER_API_KEY_VALUE: __EXPR__ secrets.OPENROUTER_API_KEY }}
          OPENAI_API_KEY_VALUE: __EXPR__ secrets.OPENAI_API_KEY }}
        run: |
          set -euo pipefail
          input_root="$RUNNER_TEMP/contextual-orchestrator-inputs"
          rm -rf -- "$input_root"
          install -d -m 0700 "$input_root"
          python3 - "$input_root" "$GITHUB_OUTPUT" <<'PY'
          import json
          import os
          from pathlib import Path
          import secrets
          import sys

          input_root = Path(sys.argv[1]).resolve(strict=True)
          output_path = Path(sys.argv[2])
          secret_env = {
              "NVIDIA_NIM_API_KEY": "NVIDIA_NIM_API_KEY_VALUE",
              "NVIDIA_NIM_API_KEY_SUB": "NVIDIA_NIM_API_KEY_SUB_VALUE",
              "BYTEZ_API_KEY": "BYTEZ_API_KEY_VALUE",
              "OPENROUTER_API_KEY": "OPENROUTER_API_KEY_VALUE",
              "OPENAI_API_KEY": "OPENAI_API_KEY_VALUE",
          }
          manifest = {}
          for credential_name, env_name in secret_env.items():
              value = (os.environ.get(env_name) or "").replace("\r", "").replace("\n", "").strip()
              if not value:
                  continue
              credential_path = input_root / f"{credential_name.lower()}.key"
              credential_path.write_text(value, encoding="utf-8")
              credential_path.chmod(0o600)
              manifest[credential_name] = str(credential_path)

          with output_path.open("a", encoding="utf-8") as output:
              if not manifest:
                  output.write("available=false\n")
                  raise SystemExit(0)
              manifest_path = input_root / "credential-manifest.json"
              manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
              manifest_path.chmod(0o600)
              token_path = input_root / "gateway-token.txt"
              token_path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
              token_path.chmod(0o600)
              output.write("available=true\n")
              output.write(f"input_root={input_root}\n")
              output.write(f"manifest={manifest_path}\n")
              output.write(f"token_file={token_path}\n")
          PY

      - name: Start Contextual-Orchestrator Strix gateway
        id: contextual_gateway
        if: steps.contextual_credentials.outputs.available == 'true'
        timeout-minutes: 10
        env:
          CONTEXTUAL_ORCHESTRATOR_SOURCE: __EXPR__ steps.contextual_source.outputs.source_root }}
          CONTEXTUAL_ORCHESTRATOR_INPUT_ROOT: __EXPR__ steps.contextual_credentials.outputs.input_root }}
          CONTEXTUAL_ORCHESTRATOR_MANIFEST: __EXPR__ steps.contextual_credentials.outputs.manifest }}
          CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE: __EXPR__ steps.contextual_credentials.outputs.token_file }}
        run: |
          set -euo pipefail
          ready_file="$RUNNER_TEMP/contextual-orchestrator-ready.json"
          gateway_log="$RUNNER_TEMP/contextual-orchestrator-gateway.log"
          rm -f -- "$ready_file" "$gateway_log"
          nohup python3 "$TRUSTED_STRIX_SOURCE/scripts/ci/strix_contextual_gateway.py" \
            --source-root "$CONTEXTUAL_ORCHESTRATOR_SOURCE" \
            --credential-manifest "$CONTEXTUAL_ORCHESTRATOR_MANIFEST" \
            --trusted-input-root "$CONTEXTUAL_ORCHESTRATOR_INPUT_ROOT" \
            --token-file "$CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE" \
            --ready-file "$ready_file" \
            --host 127.0.0.1 \
            --port 0 \
            >"$gateway_log" 2>&1 &
          gateway_pid=$!
          for attempt in $(seq 1 90); do
            if [ -f "$ready_file" ]; then
              break
            fi
            if ! kill -0 "$gateway_pid" 2>/dev/null; then
              echo "::error::Contextual-Orchestrator gateway exited during bootstrap."
              tail -n 80 "$gateway_log" || true
              exit 1
            fi
            sleep 2
          done
          if [ ! -f "$ready_file" ]; then
            echo "::error::Contextual-Orchestrator gateway did not become ready."
            tail -n 80 "$gateway_log" || true
            exit 1
          fi
          gateway_port="$(python3 - "$ready_file" <<'PY'
          import json
          from pathlib import Path
          import sys
          payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
          port = payload.get("port")
          if not isinstance(port, int) or not (1 <= port <= 65535):
              raise SystemExit("invalid gateway readiness port")
          print(port)
          PY
          )"
          curl --fail --silent --show-error "http://127.0.0.1:${gateway_port}/healthz" >/dev/null
          gateway_api_base_file="$RUNNER_TEMP/contextual-orchestrator-api-base.txt"
          gateway_model_file="$RUNNER_TEMP/contextual-orchestrator-model.txt"
          printf 'http://127.0.0.1:%s/v1' "$gateway_port" > "$gateway_api_base_file"
          printf '%s' 'openai/contextual-orchestrator' > "$gateway_model_file"
          chmod 0600 "$gateway_api_base_file" "$gateway_model_file"
          {
            echo "LLM_API_BASE_FILE=$gateway_api_base_file"
            echo "LLM_API_KEY_FILE=$CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE"
            echo "STRIX_LLM_FILE=$gateway_model_file"
            echo "CONTEXTUAL_ORCHESTRATOR_GATEWAY_PID=$gateway_pid"
            echo "CONTEXTUAL_ORCHESTRATOR_LOG=$gateway_log"
          } >> "$GITHUB_ENV"
          echo "enabled=true" >> "$GITHUB_OUTPUT"
          echo "Contextual-Orchestrator gateway is routing Strix across the discovered provider pool."

'''.replace('__EXPR__', expression_open)

workflow = workflow_path.read_text(encoding='utf-8')
marker = '      - name: Run Strix (quick)\n'
workflow = replace_once(
    workflow,
    marker,
    gateway_steps + marker,
    'insert Contextual-Orchestrator steps',
)
workflow = regex_once(
    workflow,
    r'^          STRIX_LLM_DEFAULT_PROVIDER: .*$',
    "          STRIX_LLM_DEFAULT_PROVIDER: "
    + expression_open
    + " steps.contextual_gateway.outputs.enabled == 'true' && 'openai' || steps.gate.outputs.provider_mode == 'vertex_ai' && 'vertex_ai' || steps.gate.outputs.provider_mode == 'nvidia_nim' && 'nvidia_nim' || 'openai' }}",
    'route Strix through local gateway provider',
)
workflow = regex_once(
    workflow,
    r'^          STRIX_LLM_MAX_RETRIES: 1$',
    "          STRIX_LLM_MAX_RETRIES: "
    + expression_open
    + " steps.contextual_gateway.outputs.enabled == 'true' && '0' || '1' }}",
    'disable same-model retries behind gateway',
)
workflow = regex_once(
    workflow,
    r'^          STRIX_TRANSIENT_RETRY_PER_MODEL: 2$',
    "          STRIX_TRANSIENT_RETRY_PER_MODEL: "
    + expression_open
    + " steps.contextual_gateway.outputs.enabled == 'true' && '0' || '2' }}",
    'disable wrapper transient retries behind gateway',
)
workflow = regex_once(
    workflow,
    r'^          STRIX_FALLBACK_MODELS: .*$',
    "          STRIX_FALLBACK_MODELS: "
    + expression_open
    + " steps.contextual_gateway.outputs.enabled == 'true' && ' ' || steps.gate.outputs.provider_mode == 'github_models' && 'github_models/openai/o3 github_models/openai/gpt-5-chat' || steps.gate.outputs.provider_mode == 'openai_direct' && 'github_models/openai/o3 github_models/openai/gpt-5-chat' || steps.gate.outputs.provider_mode == 'openrouter' && 'github_models/openai/o3 github_models/openai/gpt-5-chat' || steps.gate.outputs.provider_mode == 'nvidia_nim' && 'nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5 github_models/openai/o3 github_models/openai/gpt-5-chat' || '' }}",
    'delegate fallback to Contextual-Orchestrator',
)
artifact_marker = '''          if [ -f "$RUNNER_TEMP/strix_gate_console.log" ]; then
            cp "$RUNNER_TEMP/strix_gate_console.log" "$GITHUB_WORKSPACE/strix_runs/gate-console.log"
            copied_reports=1
          fi
'''
artifact_insert = artifact_marker + '''          if [ -n "${CONTEXTUAL_ORCHESTRATOR_LOG:-}" ] && [ -f "$CONTEXTUAL_ORCHESTRATOR_LOG" ]; then
            cp "$CONTEXTUAL_ORCHESTRATOR_LOG" "$GITHUB_WORKSPACE/strix_runs/contextual-orchestrator-gateway.log"
            copied_reports=1
          fi
'''
workflow = replace_once(
    workflow,
    artifact_marker,
    artifact_insert,
    'publish gateway log',
)
workflow_path.write_text(workflow, encoding='utf-8')

changelog = changelog_path.read_text(encoding='utf-8')
changelog = replace_once(
    changelog,
    '### Added\n\n',
    '### Added\n\n'
    '- Routed default Strix security scans through a commit-pinned local Contextual-Orchestrator gateway that auto-discovers the five organization provider credentials, preserves OpenAI tool-call responses, advances to another provider/model after one failed attempt, disables duplicate wrapper retries, and retains direct explicit-model dispatch as an operator override.\n',
    'update changelog added section',
)
changelog = replace_once(
    changelog,
    '### Fixed\n\n',
    '### Fixed\n\n'
    '- Classified Strix report failures by scanner semantics instead of treating every third-party `Warning` string as incomplete evidence, so a successful fallback scan is no longer discarded because Hugging Face emitted an unauthenticated-download warning.\n',
    'update changelog fixed section',
)
changelog_path.write_text(changelog, encoding='utf-8')

if gateway_test_path.exists():
    test_text = gateway_test_path.read_text(encoding='utf-8')
    test_text = test_text.replace(
        '            package_root.symlink_to(package_root, target_is_directory=True) if False else None\n',
        '',
    )
    gateway_test_path.write_text(test_text, encoding='utf-8')
