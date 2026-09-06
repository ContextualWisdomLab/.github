# ContextualWisdomLab repository README quality standard

## Purpose

Every ContextualWisdomLab repository owns its own product README because the README must be reviewed against that repository's actual code, PRD, ADRs, release state, security boundary, and license provenance. The organization control plane may define a reusable quality standard, but it must not manufacture product claims or overwrite repository-specific language.

This document is the shared review pattern for repository landing pages. It is intentionally a **quality contract, not a copy-and-paste template**. A good README should feel consistent across the organization while still making the product's bounded context, terminology, operating reality, and obligations obvious.

## Reader jobs

A root README should help four readers reach a safe next action quickly:

1. **Prospective user or buyer** — understand what problem the product solves, what it does today, and what it deliberately does not claim.
2. **Integrator** — understand how to install or consume it, the public integration boundary, and which neighboring product owns adjacent authority.
3. **Maintainer** — find the verification, architecture, contribution, security, and release evidence without exposing internal automation procedure as customer copy.
4. **Diligence reviewer** — distinguish source metadata from released artifacts, first-party licensing from dependency licensing, and implemented capability from roadmap or active-PR evidence.

The first screen should answer "what is this, why would I use it, and what can I do next?" before explaining implementation internals.

## Recommended information architecture

Use the sections that are relevant to the repository. Do not add empty headings merely for visual consistency.

### 1. Product name and one-line promise

Start with the exact repository/product casing and a one- or two-sentence value proposition written in domain language. Prefer the user outcome over an internal technology inventory.

Good:

> Generate browsable static directory indexes without running a dynamic listing service.

Weak:

> Kotlin 1.3 CLI using Clikt, Gradle, and JaCoCo.

Technology belongs later unless the technology itself is the product.

### 2. Product boundary and non-goals

State what the repository owns and, where confusion is likely, what it does not own. Keep adjacent ContextualWisdomLab products behind explicit integration boundaries rather than making a leaf repository sound like the whole platform.

Useful boundary language includes:

- source system remains authoritative;
- this library computes X but does not decide Y;
- this adapter consumes a released/versioned contract but does not own the foreign product's database;
- this documentation/source version is not release or deployment evidence.

Do not expose private table names, secret names, internal incident procedures, raw infrastructure topology, or maintainer-only automation unless a customer genuinely needs them to use the product safely.

### 3. Install or quick start

Provide the shortest **truthful, code-current** path to a useful result. Verify every command against current package metadata, lockfiles, Makefiles, build files, Compose files, CLI help, or tests.

Rules:

- do not advertise a package registry installation when only source checkout is supported;
- do not claim a hosted service exists because local Compose exists;
- do not use private sibling checkouts as a public installation contract;
- include real runtime prerequisites and version floors when they are enforced;
- keep irreversible or privileged actions out of the default quick start unless the product inherently requires them and the safety boundary is explicit.

If the repository is architecture-only or pre-runtime, say so instead of inventing an installation section. Give the reader the correct next action, such as reading the contract or running repository validation.

### 4. Common usage or public API

Show the stable user/integrator surface, not a tour of internal modules. Prefer one representative example plus links to complete reference material.

For libraries, name exported/public symbols and their responsibility. For services, name supported public endpoints only when they are current code truth. For CLI products, show the primary task-oriented commands and keep exhaustive flags in generated help/reference docs.

### 5. Architecture and integration context

Explain enough architecture to prevent misuse:

- core responsibility;
- main data/evidence flow;
- authority boundaries;
- optional versus required integrations;
- local versus external processing where relevant;
- security or privacy boundary that changes how a user should operate the product.

Link to ADRs, PRD/TRD, architecture diagrams, API schemas, or operator runbooks for detail. The README should navigate to technical authority rather than duplicate it until the two inevitably drift.

### 6. Status and quality signals

Status claims must be exact and durable.

Prefer:

- "package metadata declares version 0.5-9";
- "this is a pre-release architecture foundation";
- "the repository contains CI/SAST/security workflows; inspect the exact revision's results".

Avoid:

- treating a package version as proof of a published release;
- copying mutable PR head SHAs or run IDs into the root README;
- badges for workflows that do not exist or no longer represent the protected branch;
- unsupported benchmark, customer, certification, adoption, availability, or production-readiness claims.

Mutable exact-head integration evidence belongs in PR descriptions, gap ledgers, or generated evidence—not evergreen customer copy.

### 7. Documentation map and support

Give readers a compact map to the canonical sources that actually exist. Typical links include:

- documentation home;
- architecture / ADR index;
- API or schema reference;
- security policy / private vulnerability reporting;
- contribution guidance;
- changelog and releases;
- advanced operator reference when detailed runbooks were intentionally moved out of the README.

Do not link to planned files or Pages sites that are not published. A `docs/index.md` source is not proof that GitHub Pages is live.

### 8. Contribution guidance

State the smallest useful contributor contract: how to verify changes, what public boundary must remain stable, and where deeper maintainer instructions live. Avoid turning the customer README into an hourly-agent or PR-automation manual.

### 9. License and commercial-use boundary

A README license section is evidence-backed, not ceremonial. Before writing it, perform repository-level due diligence.

Distinguish all of the following:

1. **license of repository-authored source/documentation**;
2. **inherited/copied/derived source obligations**;
3. **third-party runtime/build/test dependency licenses**;
4. **vendored assets, models, datasets, fonts, standards-derived material, container bases, or binaries**;
5. **external service/provider terms**.

Do not say "MIT" or "Apache-2.0" merely because the organization prefers those licenses. Preserve valid existing MIT/Apache lineage. If the repository is wholly ContextualWisdomLab-authored and provenance establishes the necessary rights, add the appropriate permissive root license and matching package metadata in the authoritative PR.

If rights are inherited or uncertain, do not silently override them. Examples:

- a package whose metadata declares GPL and names upstream/external copyright holders remains GPL unless sufficient rights for relicensing are established;
- a repository MIT license does not relicense an LGPL/GPL dependency;
- a dependency's permissive license does not grant a license to otherwise unlicensed repository source;
- absence of a root `LICENSE` is a diligence prompt, not a reason to omit the question.

Under current ContextualWisdomLab commercial-intake policy, GPL/LGPL/AGPL-family source or dependencies are not an approved default inbound baseline. GPL can permit commercial use under its terms; the policy issue is copyleft/distribution compatibility, not a claim that GPL is a noncommercial license. Record the exact component and obligation, then remove/replace it when safe or preserve a precise provenance blocker and closure evidence.

## README anti-patterns

Treat these as review findings when they materially reduce clarity or accuracy:

- implementation inventory before product value;
- internal PR/agent instructions in customer copy;
- mutable check/PR status persisted as evergreen product truth;
- stale personal/upstream installation URLs after repository ownership changes;
- giant runbooks that bury the supported public workflow;
- unverified badges, customer logos, certifications, benchmarks, or release claims;
- copy-pasted architecture that contradicts the current PRD/ADR/code;
- claiming one service owns data or authorization that actually belongs to another bounded context;
- saying "commercial friendly" while a known GPL-family inbound blocker remains;
- adding a new permissive LICENSE solely because none existed, without provenance review;
- hiding third-party license obligations behind the repository's first-party license;
- creating a duplicate README PR when an existing writable product/documentation branch already owns the file.

When a README has valuable but overly detailed operator content, prefer moving that content intact to a durable advanced/reference document and linking to it from a concise landing page rather than deleting knowledge.

## Evidence checklist before editing

Read the smallest authoritative set necessary to verify claims. Depending on repository type, inspect:

- current protected/default branch and open README/documentation/license PRs;
- root README and documentation index;
- PRD/TRD/product-planning documents;
- accepted ADRs and architecture docs;
- package/build metadata (`pyproject.toml`, `package.json`, `Cargo.toml`, `DESCRIPTION`, Gradle files, etc.);
- lockfiles and dependency manifests;
- CLI/API/source symbols used by quick-start examples;
- CI/workflow commands used for verification;
- root LICENSE, NOTICE, THIRD_PARTY_NOTICES, file headers and package license metadata;
- git/upstream/fork provenance when ownership or relicensing is not obvious;
- vendored/copied/generated assets and submodules;
- live GitHub Releases/Pages state only when the README makes a release/publication claim.

Do not use dependency licenses as a shortcut for source-license analysis.

## Integration loop

README work is complete only when the branch is integrated or a real external blocker remains.

1. Search for overlapping README/documentation/license PRs before creating a new lane.
2. Update the most authoritative writable existing lane when coherent with its scope.
3. Make the smallest safe concrete improvement in the same run that confirms the defect.
4. Re-read current reviews and inline threads.
5. Inspect exact-head workflow/check results; predecessor evidence never transfers after a push.
6. Root-cause repository-owned failures and fix them rather than documenting around them.
7. When the root cause is central, move to the owning control-plane/library repository rather than adding a leaf workaround.
8. Merge through the normal protected path as soon as the unchanged exact head satisfies all applicable checks, review/thread requirements, mergeability, licensing/provenance gates, and current governance.
9. If one PR is waiting, continue another safe README/documentation lane; waiting is not completion.
10. After merge, continue to the next highest-leverage repository.

Do not bypass substantive failing tests, unresolved security findings, meaningful review objections, conflicts, required governance, or genuine provenance blockers.

## Quality bar

A README is good enough when a new reader can answer, without reading source code first:

- What problem does this product solve?
- What is the repository responsible for—and not responsible for?
- What can I safely run or integrate today?
- Where is the deeper technical authority?
- What evidence should I use to judge current quality/release state?
- How do I report a security problem or contribute?
- What license does the repository actually grant, and what important third-party/provenance limits remain?

Consistency across ContextualWisdomLab comes from answering those questions with the same evidence discipline, not from making every README sound identical.
