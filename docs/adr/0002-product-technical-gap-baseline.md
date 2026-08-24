# ADR-0002: Product and technical gap baseline

- Status: accepted
- Date: 2026-08-23
- Scope: ContextualWisdomLab/.github control plane
- Decision: Keep the buyer-facing product gap register and live PR metadata inventory in the baseline. Revalidate exact SHAs, reviews, threads, Checks, and rulesets before every merge.
- Ownership: .github owns control-plane evidence; naruon and product repositories own product behavior and consumer smoke.
- Figma File ID: N/A. This repository has no customer UI. A UI-owning repository must replace N/A with its real Figma File ID before a UI PR is accepted and must provide Storybook and design-token evidence.
- Consequence: The document is an operational snapshot, not a merge authorization or substitute for protected GitHub review. Hourly agents must re-collect exact head SHAs, reviews, threads, and required Checks before merge. Papers/standards live in `docs/doctoring/product-technical-gap-baseline.md` and must remain consistent with this ADR.
