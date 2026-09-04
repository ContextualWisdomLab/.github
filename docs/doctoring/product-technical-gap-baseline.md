# Product and technical gap baseline — doctoring

Status: accepted. Scope: ContextualWisdomLab/.github control plane.
Companion ADR: [`docs/adr/0002-product-technical-gap-baseline.md`](../adr/0002-product-technical-gap-baseline.md).
Live snapshot: [`docs/product-technical-gap-baseline.md`](../product-technical-gap-baseline.md).

## Decision

Keep a SHA-bound open-PR inventory and a 구매자-체감 Gap register in-repo so
hourly agents refresh current heads instead of private memory. The inventory is
an operational snapshot. It is not merge authorization, not a substitute for
current-head OpenCode/Noema approval, and not a reason to skip required Checks.

Figma File ID: N/A. This repository has no customer UI. A UI-owning repository
must record its real Figma File ID in its own ADR before a UI PR is accepted
and must provide Storybook scene/edge-case events plus design-token evidence.

PII masking is not the privacy strategy. Use purpose-bound access lease,
field-level encryption or tokenization, consented minimal-disclosure
consequence, audit, and revocation (CSAP / SOC 2 / ISO 27001 alignment).

`COPILOT_GITHUB_TOKEN` is unused. Review-agent credentials stay independent of
repair/orchestrator credentials.

## Exact-head papers and standards (APA 7th)

These sources bind the Gap register and AI-plane TRD. They must not contradict
the protected `main` control-plane contracts.

American Institute of Certified Public Accountants. (2017). *2017 trust
services criteria for security, availability, processing integrity,
confidentiality, and privacy*. AICPA.

International Organization for Standardization. (2022). *ISO/IEC 27001:2022
information security, cybersecurity and privacy protection—Information
security management systems—Requirements*. ISO.

International Organization for Standardization. (2023). *ISO/IEC 42001:2023
information technology—Artificial intelligence—Management system*. ISO.

National Institute of Standards and Technology. (2023). *Artificial
intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1). U.S.
Department of Commerce. https://doi.org/10.6028/NIST.AI.100-1

World Wide Web Consortium. (2023). *Web Content Accessibility Guidelines
(WCAG) 2.2*. https://www.w3.org/TR/WCAG22/

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N.,
Küttler, H., Lewis, M., Yih, W.-t., Rocktäschel, T., Riedel, S., & Kiela, D.
(2020). Retrieval-augmented generation for knowledge-intensive NLP tasks.
*Advances in Neural Information Processing Systems, 33*, 9459–9474.

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H.,
Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., &
Clanuwat, T. (2026). *Sakana Fugu technical report* [Technical report]. arXiv.
https://doi.org/10.48550/arXiv.2606.21228

Zhang, S., Yu, Y., Li, Y., Zhao, W., Yang, Y., Zhang, Y., & Liu, T. (2025).
*Conductor: Learning to route multi-agent workflows* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026).
*TRINITY: An evolved LLM coordinator* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2512.04695

Higgins, S. S., Crepalde, N., & Fernandes, L. (2021). Segmented multiplexity:
A research agenda for multiplexity beyond the average. *PLOS ONE, 16*(9),
e0257527. https://doi.org/10.1371/journal.pone.0257527

Local Zotero was not reachable from this session. Citations use the OA/DOI
records above; add the PDFs to the local Zotero library when the API is up.

## Next action

Refresh [`docs/product-technical-gap-baseline.md`](../product-technical-gap-baseline.md)
from live `gh pr list` before acting on any row. Then: 리뷰 확인 → 수정 →
Checks 재검증 → 병합 → 다음 개발. Wait for OpenCode/Strix/Noema without
stopping other PRs or Gap work.
