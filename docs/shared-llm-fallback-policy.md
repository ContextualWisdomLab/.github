# Shared LLM fallback policy

Noema, OpenCode Agent, and Strix now consume one versioned model-ordering
contract while retaining their existing transports, reviewer identities,
credential scopes, output validators, security checks, and evidence formats.
The shared policy is implemented by the pinned `contextual-orchestrator`
module under `vendor/contextual-orchestrator` and exposed to workflows through
`scripts/ci/contextual_fallback_policy.py`.

## Invariant

For every agent and repository visibility, the planner produces this order:

1. all eligible `free` candidates, by numeric priority;
2. all eligible `paid` candidates, by numeric priority;
3. declaration order as the final stable tie-breaker.

A paid candidate can never overtake an eligible free candidate. Provider or
model failure advances to the next candidate only through the agent's existing
fail-closed transport and output-validation path. A response is never accepted
merely because a provider returned HTTP success.

## Agent adapters

### Noema

For public repositories with `NVIDIA_NIM_API_KEY`, Noema attempts the approved
NVIDIA hosted models in this order:

1. `nvidia/nemotron-3-ultra-550b-a55b`
2. `nvidia/llama-3.3-nemotron-super-49b-v1.5`
3. `nvidia/nemotron-3-super-120b-a12b`
4. an explicitly configured custom model, when present

The custom configuration remains the final paid/contracted fallback. Private
repositories never become eligible for the public NVIDIA hosted candidates.
The wrapper delegates every attempt to the unchanged Noema OpenAI-compatible
request, JSON verdict validator, current-head check gate, and reviewer token.

### OpenCode Agent

The existing configured pool is intersected with the shared manifest, then
reordered without changing provider clients or credentials:

1. public NVIDIA NIM trial candidates;
2. public `opencode-free/*` candidates;
3. GitHub Models candidates while the organization is operating within its
   included rate-limited quota and paid usage is disabled;
4. OpenCode Zen, direct OpenAI, and paid OpenRouter candidates.

Private and internal repositories exclude candidates declared public-only.
The unchanged OpenCode core still owns retries, timeout budgets, structured
review normalization, evidence sealing, secret masking, and the prohibition on
synthetic approval after provider exhaustion.

### Strix

Strix keeps its existing scan gate and security-report semantics. The shared
policy is applied in `strix_model_utils.sh` after the trusted workflow creates
model and key files, but before the gate resolves the primary model. Public NIM
models and configured GitHub Models quota candidates are ordered before paid
OpenAI or Vertex candidates. The original Strix gate continues to select the
correct provider-specific key and API base per attempt, preserve findings,
apply severity thresholds, and fail closed on provider warning or timeout
signals.

## Supply-chain pin

The integration does not perform a mutable branch checkout at runtime. It
vendors only the policy modules from
`ContextualWisdomLab/contextual-orchestrator` commit
`82ea37ee2673111b0a2f25642d637a305473f642`, plus a minimal integration facade.
`VENDOR_RECEIPT.json` records every expected Git blob identity. The adapter
verifies the exact repository, commit, file map, regular-file status, and blob
identity before importing the module. Unknown receipt fields, symlinks,
duplicate JSON keys, source drift, or an already imported module outside the
verified vendor root stop the workflow.

## Updating the policy

1. Confirm provider billing and availability from current primary documentation.
2. Update `contextual-orchestrator` first and obtain an exact reviewed commit.
3. Copy only the required policy files and license.
4. Recalculate Git blob identities with Git's `blob <length>\0<content>` format.
5. Update `VENDOR_RECEIPT.json`, adapter constants, and
   `config/llm-fallback-policy.json` in the same PR.
6. Run the policy, Noema, OpenCode, and Strix contract tests on the exact head.
7. Treat a provider's transition from included/free quota to metered use as a
   cost-tier change. Never infer cost from a model-name suffix.

## Operational boundaries

- `free` means the operator has verified that the candidate does not currently
  incur inference charges under the configured account contract. It does not
  mean unlimited capacity or permanent availability.
- GitHub Models is classified as free only while paid usage is disabled and the
  included rate-limited quota is in effect. Enabling paid usage requires a
  manifest update before merge.
- NVIDIA hosted API candidates are public-repository-only because they use a
  hosted trial/prototyping endpoint. Private code remains on explicitly
  approved private-capable providers.
- The policy reads only whether named credentials are non-empty. It never
  serializes credential values, provider response bodies, prompts, or code.
- An empty or drifted candidate pool is an error, not an approval or a silent
  fallback to an undeclared model.
