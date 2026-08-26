# ADR-0002: Product and technical gap baseline

- Status: accepted
- Date: 2026-08-23
- Scope: ContextualWisdomLab/.github control plane
- Decision: Keep the buyer-facing product gap register and live PR metadata inventory in the baseline. Revalidate exact SHAs, reviews, threads, Checks, and rulesets before every merge.
- Ownership: .github owns control-plane evidence; naruon and product repositories own product behavior and consumer smoke.
- Figma File ID: N/A. This repository has no customer UI. A UI-owning repository must replace N/A with its real Figma File ID before a UI PR is accepted and must provide Storybook and design-token evidence.
- Consequence: The document is an operational snapshot, not a merge authorization or substitute for protected GitHub review. Hourly agents must re-collect exact head SHAs, reviews, threads, and required Checks before merge. Papers/standards live in `docs/doctoring/product-technical-gap-baseline.md` and must remain consistent with this ADR.

## Amendment: central Strix fallback contract (2026-08-25)

The current `main` workflow (`a724582`) intentionally replaced the unavailable
direct-OpenAI `gpt-5.6-luna` fallback with `gpt-5.4`, but the required-workflow
smoke script still asserted the retired model. The privileged OpenCode model
pool also retained the retired candidate while its contract tests had already
moved to `gpt-5.4`. This mismatch failed consumer Strix checks, including
ContextualWisdomLab/disksage#247, before any target-repository security
analysis ran. The workflow, smoke contract, model-pool configuration, and
regression tests now share `gpt-5.4`; the change does not weaken provider
failure or vulnerability fail-closed behavior.

## Amendment: autofix model ownership boundary (2026-08-26)

The write-capable PR autofix worker enables only the OpenAI-compatible
contextual-orchestrator gateway. The central workflow pins the gateway source,
verifies its reviewed license identity, binds it to loopback, and fails closed
unless authenticated model discovery returns a usable catalog. Provider keys
are passed only to the isolated sidecar and are removed before OpenCode runs;
the established review, OIDC, branch-write, independent-approval, and protected
merge credential contracts are unchanged. Product-specific hourly callers do
not duplicate a repository-local product-development writer when one already
owns the zero-open-PR continuation.
