<p align="center">
  <img src="./assets/context-wisdom-lab-logo.svg" alt="맥락지혜 연구실 · Contextual Wisdom Lab logo" width="720">
</p>

# 맥락지혜 연구실 · Contextual Wisdom Lab

**We build evidence-centered software that turns scattered context into reviewable decisions and safe action.**

맥락지혜 연구실은 메일, 문서, 일정, 데이터, 운영 증거처럼 흩어진 맥락을 연결해 사람이 더 빨리 이해하고, 근거를 확인하고, 안전하게 행동할 수 있도록 돕는 제품과 기반 기술을 만듭니다.

[Homepage](https://contextualwisdomlab.github.io/) · [GitHub](https://github.com/ContextualWisdomLab) · [Naruon](https://github.com/ContextualWisdomLab/naruon)

## Start here

| Product | What it owns |
| --- | --- |
| **[Naruon](https://github.com/ContextualWisdomLab/naruon)** | AI email workspace that connects mail, attachments, calendar, tasks, and bounded action intent while customer systems remain sources of truth. |
| **[contextual-orchestrator](https://github.com/ContextualWisdomLab/contextual-orchestrator)** | Model-agent orchestration control plane behind one OpenAI-compatible API, including routing, delegation, verification, and synthesis. |
| **[Keyverse](https://github.com/ContextualWisdomLab/keyverse)** | Identity and federation authority for passwordless accounts, inbound federation/SCIM, and outbound OIDC/OAuth contracts. |
| **[Noema](https://github.com/ContextualWisdomLab/noema)** | Evidence-producing credential and maintenance control plane for governed repository automation and short-lived capability. |
| **[AppGuardrail](https://github.com/ContextualWisdomLab/appguardrail)** | Security guardrails and review evidence for applications built with AI-assisted development tools. |

These products compose through explicit contracts. A convenient integration does not transfer source-of-truth ownership, credential authority, security authority, or scientific validity from one product to another.

## Context, evidence, and enterprise structure

- **[LineageWeave](https://github.com/ContextualWisdomLab/LineageWeave)** reconstructs record-lineage structures from scattered, weakly linked evidence. Its protected source currently describes a demo-prototype boundary rather than a production-data claim.
- **[Semantic Data Portal](https://github.com/ContextualWisdomLab/semantic-data-portal)** is an ontology-driven graph-and-vector semantic catalog for finding, browsing, and governing datasets and concepts.
- **[Orgmetra](https://github.com/ContextualWisdomLab/Orgmetra)** develops evidence-centered HRIS/HCM contracts around people, employment, organizations, jobs, positions, and assignments while keeping identity and adjacent product authority separate.
- **[ConceptWeave](https://github.com/ContextualWisdomLab/ConceptWeave)** develops governed ontology and semantic-layer engineering around observed evidence, proposals, deterministic validation, review, and publication boundaries.
- **[ELUNVERA](https://github.com/ContextualWisdomLab/ELUNVERA)** develops an evidence-centered CRM and relationship-intelligence contract while keeping model output reviewable rather than silently authoritative.

## Measurement and decision science

- **[fast-mlsirm](https://github.com/ContextualWisdomLab/fast-mlsirm)** is an early high-performance psychometric toolkit for multidimensional latent-space item-response modeling, simulation, estimation, diagnostics, and recovery evidence.
- **[TEPP](https://github.com/ContextualWisdomLab/TEPP)** is the Temporal Event Psychometrics Platform for temporal, relational, multilingual measurement with Rust-owned statistical and psychometric arithmetic.
- **[RankWeave](https://github.com/ContextualWisdomLab/RankWeave)** provides independently operable ranking, fusion, evaluation, and report contracts for applications that need evidence-backed ranking behavior.

Scientific and statistical outputs are evidence, not automatic decision authority. Interpretation, fairness, validity, and release claims stay bound to the methods, data, assumptions, and verification that actually support them.

### Why AI participates in judgment and decision-making

Contextual Wisdom Lab does not use AI because a model is presumed wiser than a person. We use AI to turn repeated judgments from implicit impressions into explicit, testable, and reproducible procedures.

Grove et al. (2000) meta-analyzed 136 studies comparing clinical judgment with mechanical prediction—formal statistical, actuarial, or algorithmic rules that combine data in a specified way. Mechanical methods were about 10% more accurate on average, substantially outperformed clinical judgment in 33%–47% of studies, and were substantially worse in only 6%–16%. The finding supports a general preference for an appropriate mechanical procedure when it has been validated for the decision and its consequences. It does **not** establish that modern language models are generally superior to people or should receive unbounded authority.

For our products, an AI-assisted judgment must preserve:

- traceable source evidence and data lineage;
- explicit criteria, versioned rules, and reproducible execution;
- uncertainty, counterevidence, alternatives, and the ability to abstain;
- cost-sensitive evaluation of false positives and false negatives;
- human or separately governed approval where consequences require it; and
- post-deployment monitoring, subgroup error analysis, and a path to review or appeal.

AI is therefore a formalized decision-support mechanism, not a substitute for responsibility. A model output remains evidence until an explicitly governed process grants it decision authority.

## Infrastructure and control planes

- **[EgressWeave](https://github.com/ContextualWisdomLab/EgressWeave)** provides explicit, reviewable outbound HTTP authority instead of ambient network trust.
- **[wardnet](https://github.com/ContextualWisdomLab/wardnet)** develops gateway and security-operations control-plane capabilities with product and external-security boundaries kept explicit.
- **[metering-billing-platform](https://github.com/ContextualWisdomLab/metering-billing-platform)** develops metering, billing, entitlement, and finance-operation evidence contracts.
- **[governance-risk-compliance](https://github.com/ContextualWisdomLab/governance-risk-compliance)** develops policy, control, evidence, and governance workflows without treating documentation or mappings as certification.
- **[context-graph-contracts](https://github.com/ContextualWisdomLab/context-graph-contracts)** defines shared interoperability contracts without becoming an application or foreign system of record.

## Working principles

1. **Evidence before authority.** A model answer, score, scanner result, document, or workflow status does not become a business, security, scientific, legal, or merge decision merely because it exists.
2. **Source systems stay authoritative.** Products integrate through versioned contracts and anti-corruption boundaries instead of copying foreign truth or depending on cross-service application-table SQL.
3. **Human judgment remains visible.** We aim to reduce context reconstruction and repetitive work while preserving review points where consequences require a person or an explicitly governed authority.
4. **Fail closed on uncertainty.** Missing provenance, stale identity, ambiguous permissions, unsupported scientific evidence, and unverified release state should stop a claim or action rather than be filled in heuristically.
5. **Commercial provenance matters.** Repository source licensing and third-party software/assets are reviewed separately. A permissive project license does not relicense an incompatible dependency.

## Research lens

We use DIKW as a set of product checkpoints rather than an automatic hierarchy:

**records → contextualization → judgment points → action**

The practical questions are simple: Did we retain the source evidence? Did we add the context needed to interpret it? Did we expose uncertainty and counterevidence? Did we narrow the result to a reviewable decision or next action?

Selected background:

- Ackoff, R. L. (1989). *From data to wisdom*. Journal of Applied Systems Analysis, 16(1), 3–9.
- Baskarada, S., & Koronios, A. (2013). Data, information, knowledge, wisdom (DIKW): A semiotic theoretical and empirical exploration. *Australasian Journal of Information Systems, 18*(1). https://doi.org/10.3127/ajis.v18i1.748
- Frické, M. (2009). The knowledge pyramid: A critique of the DIKW hierarchy. *Journal of Information Science, 35*(2), 131–142. https://doi.org/10.1177/0165551508094050
- Brienza, J. P., Kung, F. Y. H., Santos, H. C., Bobocel, D. R., & Grossmann, I. (2018). Wisdom, bias, and balance: Toward a process-sensitive measurement of wisdom-related cognition. *Journal of Personality and Social Psychology, 115*(6), 1093–1126. https://doi.org/10.1037/pspp0000171
- Grove, W. M., Zald, D. H., Lebow, B. S., Snitz, B. E., & Nelson, C. (2000). Clinical versus mechanical prediction: A meta-analysis. *Psychological Assessment, 12*(1), 19–30. https://doi.org/10.1037/1040-3590.12.1.19

## Repository and license boundary

This organization profile is a curated entry point, not an exhaustive product catalog and not release, deployment, customer, certification, or commercial-readiness evidence. The owning repository remains authoritative for each product's current behavior, maturity, installation path, security posture, and license.

The ContextualWisdomLab `.github` repository and this profile are licensed under the **MIT License**. Linked repositories and all third-party packages, assets, standards, models, datasets, and services retain their own terms; this profile does not relicense them.

## Founder

Founded by [Seongho Bae](https://github.com/seonghobae). ORCID: [0000-0003-2484-3881](https://orcid.org/0000-0003-2484-3881).
