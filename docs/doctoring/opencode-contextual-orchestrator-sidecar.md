# OpenCode → contextual-orchestrator sidecar (next step)

검토 기준일: **2026-08-17**

## Decision

GitHub Models stays unused. The intended long-term OpenCode provider is
ContextualWisdomLab/contextual-orchestrator, an OpenAI-compatible
`/v1/chat/completions` hub. Until that sidecar exists, central review keeps
**NIM-direct** as the default (`NVIDIA_NIM_API_KEY` → `NVIDIA_API_KEY`).
`COPILOT_GITHUB_TOKEN` is not introduced.

This pull request does not start the sidecar and does not block OriginWeave
#47 quality fixes or the 7200s NIM timeout on it.

## Optional path already in dispatch

If `vars.CONTEXTUAL_ORCHESTRATOR_URL` is set,
`scripts/ci/attach_contextual_orchestrator_provider.py` attaches one
OpenAI-compatible `contextual-orchestrator` provider block to the isolated
catalog. The helper fails closed on GitHub Models hosts, embedded
credentials, non-http(s) URLs, and non-loopback `http`. Unset URL is a
no-op. Default `model` / `small_model` and `OPENCODE_MODEL_CANDIDATES`
stay NIM-direct.

## Next step (do not do it in this PR)

1. The review job starts a ContextualWisdomLab/contextual-orchestrator sidecar.
2. The sidecar registers these five organization secrets into its KV:
   NIM, NIM_SUB, OpenAI, OpenRouter, and Bytez.
3. OpenCode talks only to that sidecar URL. It does not receive the five
   upstream secrets and does not fall back to GitHub Models.

## References

ContextualWisdomLab/contextual-orchestrator is the org LLM routing hub
(LiteLLM-plus). See [`docs/CWL-MASTER-CONTEXT.md`](../CWL-MASTER-CONTEXT.md)
§3 and [`docs/nvidia-nim-opencode-hotfix.md`](../nvidia-nim-opencode-hotfix.md).
