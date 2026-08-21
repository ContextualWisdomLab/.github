# Contextual Orchestrator OpenCode gateway

The trusted OpenCode review job starts `contextual-orchestrator` from the
pinned predecessor commit `d3a27db0a69f09f245a19a189ec41d3aa2f6b2fc` from
contextual-orchestrator#790. After that predecessor merges, this pin must be
replaced with the resulting protected `main` SHA. The sidecar binds only
to `127.0.0.1:18080`, registers any available provider keys in its process-local
KV bootstrap, discovers models across Bytez, both NVIDIA NIM credentials,
OpenRouter, and OpenAI, then serves the existing OpenAI-compatible review
request through the `contextual-orchestrator` model candidate.

```mermaid
flowchart LR
  A["GitHub Actions trusted review job"] --> B["Pinned contextual-orchestrator sidecar"]
  B --> C["KV bootstrap and model discovery"]
  C --> D["Cost-ranked provider pool"]
  D --> E["OpenCode contextual-orchestrator candidate"]
  E --> F["Existing provider-qualified fallbacks"]
```

The gateway candidate is first in the model pool only for public repositories,
after the pinned checkout succeeds, the sidecar reaches the unauthenticated
`/healthz` liveness check, and an authenticated `/v1/models` response contains
at least one non-empty model id. `/healthz` is liveness only. A missing or
unreadable pinned revision is non-fatal:
the gateway candidate is skipped and the established provider-qualified pool
remains available. Private repositories never start or select the gateway,
because its auto-discovered catalog includes providers excluded by the review
workflow's private-source retention policy. Review publication, current-head
binding, independent approval, Strix, and branch protection are unchanged.
`COPILOT_GITHUB_TOKEN` is not used.

The sidecar receives the five provider credentials only in the model-execution
step. It does not receive review-write tokens, and the generated local bearer
token is masked and used only for loopback inference. Persistent production
credential storage remains the gateway deployment's existing KV boundary; this
runner bootstrap is intentionally process-local and ephemeral.

## References

GitHub. (n.d.). *Building and testing Python*. Retrieved August 20, 2026,
from https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python

GitHub. (n.d.). *Using secrets in GitHub Actions*. Retrieved August 20, 2026,
from https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 20, 2026, from
https://opencode.ai/docs/

ContextualWisdomLab. (n.d.). *contextual-orchestrator* [Source repository].
Retrieved August 20, 2026, from
https://github.com/ContextualWisdomLab/contextual-orchestrator
