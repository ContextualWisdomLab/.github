# Review skill source selection — 2026-09-07

The discovery source is https://x.com/DivyanshT91162/status/2096703758256541974.
It lists ten projects; this change adopts three instruction procedures, not ten
plugins. The selection is based on the inspected skill implementations and
licenses, not the post's popularity or performance claims.

The portable [upstream record](../../.agents/skills/cwl-review-evidence/references/upstream_sources.md)
is the canonical source/commit/blob/APA-reference/license and exclusion register.
The [ADR](../adr/20260907_review_skill_projection.md) records the implementation,
existing consumer seam, parent PR, alternatives, acceptance and rollout limits.

## Candidate disposition

| Post item | Decision for this central review slice |
|---|---|
| Archify | Defer executable adoption. Its public repository describes an agent skill for architecture/sequence/data-flow diagrams with HTML output. Any renderer integration must preserve DiagramWeave ownership and the isolated artifact-analysis boundary; this patch does not install or certify it. |
| OpenMAIC | Not selected for this instruction-only review slice; no runtime or security suitability claim is made. |
| DeepSeek Harness | Not selected as a replacement review runtime; CO routing and existing authorization boundaries remain unchanged. This is not a compatibility assessment of that harness. |
| Ponytail | Adopt a bounded complexity/reuse procedure, not its complete plugin or stand-alone approval conventions. |
| Agent Skills | Adopt code-review-and-quality procedures, with local contracts taking precedence over generic numerical heuristics. |
| OmniVoice Studio | Not selected for central code review; no audio runtime or voice capability is installed. |
| Scientific Agent Skills | Adopt scientific-critical-thinking guidance for applicable changes, without its optional external-provider path. |
| Orca | Not selected; this change does not establish the exact upstream/runtime integration or its security posture. |
| MiniMind | Not selected for the trusted review runtime; no model training or inference environment is introduced. |
| God's Eye View | Not selected for central code review; no surveillance or data-collection capability is introduced. |

Archify public source observed: https://github.com/tt-a1i/archify.
The non-selected items are scope dispositions, not a full audit or a judgment
that they are unsuitable for every CWL product. Do not infer missing repository
URLs from truncated social links or treat this table as an executable allowlist.

## Known operating constraints

The main observation and PR #1655 source are separate snapshots. The child uses
#1655 to preserve its control-schema repair rather than resetting both prompts
to main. Existing Ponytail operating-playbook work in #1885 and workstation
integration in macos_utility_packs#6 are complementary, not duplicated installers.
Noema/Strix integration and the baseline-writer append remain explicit handoffs.
No protected merge, release, live hosted consumption, model-quality improvement,
or organization-wide native-plugin installation is claimed by these documents.
