# Upstream source record

Observed: 2026-09-07. Adoption mode: instruction-only CWL adaptation.
Discovery source: https://x.com/DivyanshT91162/status/2096703758256541974
The social post identifies candidates; it is not implementation or safety evidence.

## Immutable inputs

| Source | Commit | Reviewed skill blob | License blob |
|---|---|---|---|
| DietrichGebert/ponytail | `974d940a1c5344210874150b98ff0d2c861fab6a` | `e137a855bd87119a4517895a1000a59b0999e1b8` | `715d483338cea4365f0d91a27799cf61226d6bcf` |
| addyosmani/agent-skills | `48cb1168aeaaa70dfc2bbf709eddfa2a8ed8129a` | `7dfa56362fa65fff450ee5aa02393b85b9c26d85` | `d67778ada6b9cda6227e9130da182c13e73c8b2e` |
| K-Dense-AI/scientific-agent-skills | `9cf7d9aea7d84754db4c167ab04b299d33c444bc` | `c376afc69fd93c742972af4003da279ec1f5ef55` | `eb246475fd5a66b9bb56176f3a718984632dd98d` |

The former `K-Dense-AI/claude-scientific-skills` address redirects to
`K-Dense-AI/scientific-agent-skills`. These hashes identify the inspected
upstream files, not a claim that all files or plugins in those repositories
were audited. There is no runtime fetch, auto-update or installer in this pack.

## Accepted and excluded semantics

**Ponytail:** use the complexity-review lens only after tracing behavior and
existing ownership. The inspected `ponytail-review` explicitly excludes
correctness/security/performance, uses line-reduction scoring, and gives a
substring email-check example. CWL does not adopt those as approval standards.
Do not remove domain Repository/ACL boundaries based on implementation count,
weaken input validation, or replace coverage with a smoke test. No lifecycle
hooks, plugin mode switches, install commands or marketing benchmark claims are
included.

**Agent Skills:** use tests to understand intended behavior, evaluate the five
review axes, and name concrete structural remedies. Generic diff-size targets,
caller-count rules and test-pyramid ratios are not CWL gates. Host control
schemas and local evidence rules take precedence. This pack includes no
upstream hook or plugin runtime and needs no omitted repository-level checklist.

**Scientific Agent Skills:** adopt methodology, bias, uncertainty, claim/evidence
separation and proportionate critique. The inspected entry is analytical
guidance; its optional schematic path sends prompts to OpenRouter. That path,
write permissions, package installation and external account promotion are
excluded. GRADE/Cochrane applicability must be established, not presumed for
software or psychometric studies. CWL adds its own estimand, multilevel,
multiple-membership, time-leakage and failure-denominator constraints; these
are explicit local adaptations, not quotations of the upstream entry.

## References (APA 7th)

DietrichGebert. (2026). *Ponytail review* [Agent skill, commit 974d940a1c5344210874150b98ff0d2c861fab6a]. GitHub. https://github.com/DietrichGebert/ponytail/blob/974d940a1c5344210874150b98ff0d2c861fab6a/skills/ponytail-review/SKILL.md

Osmani, A. (2026). *Code review and quality* [Agent skill, commit 48cb1168aeaaa70dfc2bbf709eddfa2a8ed8129a]. GitHub. https://github.com/addyosmani/agent-skills/blob/48cb1168aeaaa70dfc2bbf709eddfa2a8ed8129a/skills/code-review-and-quality/SKILL.md

K-Dense Inc. (2026). *Scientific critical thinking* (Version 1.3) [Agent skill, commit 9cf7d9aea7d84754db4c167ab04b299d33c444bc]. GitHub. https://github.com/K-Dense-AI/scientific-agent-skills/blob/9cf7d9aea7d84754db4c167ab04b299d33c444bc/skills/scientific-critical-thinking/SKILL.md

These are software-procedure references, not primary scientific evidence for a
reviewed estimator, benchmark or clinical claim. The year records the inspected
2026 snapshot; it does not infer the initial publication date of every file.

## License notices

All three inspected licenses are MIT. The common permission text below applies
to the respective upstream material and its adaptations with these notices:

- Ponytail: Copyright (c) 2026 DietrichGebert
- Agent Skills: Copyright (c) 2025 Addy Osmani
- Scientific Agent Skills: Copyright (c) 2025 K-Dense Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
