# Pinned awesome-copilot methods in central review inputs

- Status: Proposed
- Date: 2026-09-08
- Deciders: ContextualWisdomLab maintainers
- Owner: ContextualWisdomLab/.github

## Context and decision

In the context of central OpenCode, Noema and Strix reviews, facing a requirement
that reviewers consistently use github/awesome-copilot skills despite different
prompt interfaces, we decided for complete pinned review-method text delivered
by a common trusted loader and against a URL-only instruction, workstation-only
installation or automatic upstream plugin installation, to achieve reproducible
method delivery without additional execution authority, accepting roughly 53 KB
of additional prompt content and deliberate reviewed updates of the pinned input.

## Consequences and alternatives

The central control plane owns the bundle; consumers keep their existing thin
workflow and published revision contract. The Python loader is CI input assembly,
not a scientific, security-analysis or performance execution engine. It uses the
existing Python runtime and standard library; no new dependency is introduced.

The three selected methods cover engineering maintenance, behavioral test gaps
and security. All selected SKILL.md bytes and five security references are
retained with the MIT license. The wrapper explicitly constrains upstream edit,
installation, output-template and target-instruction directives. Static security
watchlists remain hypotheses requiring current independent evidence.

Workstation-only native discovery was rejected because Noema builds HTTP messages
and Strix receives command arguments. Mutable network downloads were rejected
because an upstream update must not change a protected review silently. Copying
methods separately into every repository was rejected because ownership and
updates would diverge. Loading every unrelated upstream skill was rejected:
reviewers receive the relevant complete methods, not deployment or generation
authority. PR #2012's distinct source selection remains intact and is not closed
or claimed as inherited by this change.

## Verification and release

The [runbook](../doctoring/awesome_copilot_review_inputs.md) defines failure
reproduction, executable consumption checks and hosted rollout requirements.
Local delivery checks cannot prove model quality or protected deployment. This
ADR remains Proposed until the normal protected lifecycle and live review
receipts demonstrate delivery from the released central revision.

Strix CLI-only instructions can disappear at child construction. We selected the
published `register_skill_dir` extension: preserve all original scan-mode bytes
and append the verified methods in a trusted, read-only directory kept for the
CLI lifetime. Real pinned 1.5.3 root/child/grandchild/resume probes pass across all
modes and both inheritance settings. A new upstream API or package patch was
rejected because the existing owner API supports the required propagation.
Shared gate integration and hosted adoption remain unverified; the ADR stays
Proposed. OpenCode uses native global instructions and permits delegation rather
than treating a blanket task denial as an acceptable propagation mechanism.
