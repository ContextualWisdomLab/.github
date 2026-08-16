# Doctoring — automation control-plane standards baseline

Research date: 2026-08-09
Scope: architecture, requirements engineering, product quality, secure development, CI/CD supply chain, GitHub trust, AI-assisted review, observability, and testing

## Version decisions

- NIST SP 800-218 version 1.1 is the current **final** Secure Software Development Framework. The proposed version 1.2 was published as an initial public draft on 2025-12-17, so this repository treats it as informative until final.
- NIST SP 800-92 (2006) remains the final log-management publication. SP 800-92 Rev. 1 was published as an initial public draft on 2023-10-11 and remains informative; it does not silently supersede the final publication.
- SLSA version 1.2 is the current SLSA specification. The architecture uses its provenance and verification concepts without claiming a SLSA level that has not been demonstrated.
- ISO/IEC/IEEE 42010:2022 is the architecture-description baseline; the documentation separates stakeholders, viewpoints, models, and concerns.
- ISO/IEC/IEEE 29148:2018 is the current published requirements-engineering baseline and was confirmed in 2024. The Edition 3 Draft International Standard under development in 2026 is informative only until published; draft requirements MUST NOT be reported as the current final baseline.
- ISO/IEC 25010:2023 is the current product-quality-model baseline used to structure relevant correctness, reliability, security, maintainability, compatibility, usability/interaction, performance-efficiency, flexibility, and safety quality concerns without claiming formal conformance.
- ISO/IEC 27001:2022 and ISO/IEC 42001:2023 are management-system alignment references. ISO/IEC 27002:2022 supplies information-security control guidance, including the logging, monitoring, access, and incident concerns relevant here; ISO states that 27002 itself is guidance and is not certifiable.
- The software-testing baseline names concrete published parts rather than an unspecified series: ISO/IEC/IEEE 29119-1:2022 for general concepts and ISO/IEC/IEEE 29119-2:2021 for test processes. Other 29119 parts are not implied unless separately cited and mapped.
- SOC 2 alignment refers specifically to the AICPA 2017 Trust Services Criteria with revised points of focus (2022), not to a self-awarded certification or report.
- CSAP means the Korean Cloud Security Assurance Program (클라우드서비스 보안인증). It is considered only for an in-scope cloud service and applicable Korean public-sector use; this repository is not a CSAP assessment or certificate.
- GitHub's current secure-use guidance warns against executing untrusted content under `pull_request_target` or `workflow_run` privilege. The central metadata-bootstrap/default-branch-dispatch split follows that boundary.
- OpenTelemetry Specification 1.59.0 and its stable log data model are the current observability references observed on the research date.

## Applied implications

| Source | Applied control |
|---|---|
| NIST SSDF 1.1 | protected development environment, provenance, verification, vulnerability response, continuous improvement |
| NIST SSDF 1.2 initial public draft | informative gap review only; no draft practice is reported as a final requirement |
| NIST SP 800-204D | stage-separated CI/CD supply-chain controls, integrity verification, policy enforcement, evidence |
| NIST SP 800-92 final / Rev. 1 draft | log generation, transmission, storage, access, disposal, incident use, and retention planning; the draft is informative only |
| SLSA 1.2 | immutable provenance identity, artifact/source verification, no unsupported level claim |
| ISO/IEC/IEEE 42010:2022 | viewpoint-based architecture, explicit stakeholders/concerns, model consistency |
| ISO/IEC/IEEE 29148:2018 | explicit stakeholder/system/software requirements, requirement attributes, traceability, validation, and controlled change |
| ISO/IEC/IEEE 29148 Edition 3 DIS | informative future-gap review only until publication; never substitute draft text for the current final edition |
| ISO/IEC 25010:2023 | product-quality characteristics drive PRD/NFR/test/operability quality coverage and buyer-visible quality gaps |
| ISO/IEC 27001:2022 | risk, least privilege, supplier/change/logging/incident governance |
| ISO/IEC 27002:2022 | guidance for information-security controls; no 27002 certification claim |
| ISO/IEC 42001:2023 | human accountability, AI provider governance, validated model output, continual improvement |
| GitHub secure-use and OIDC guidance | trusted workflow source, untrusted input handling, minimal token permissions, short-lived federation |
| OpenTelemetry | correlation by time and execution identity across logs, metrics, and traces |
| ISO/IEC/IEEE 29119-1:2022 and 29119-2:2021 | common testing concepts and governed test processes across lifecycle models |
| AICPA 2017 Trust Services Criteria (revised points of focus, 2022) | evidence design for security, availability, processing integrity, confidentiality, and privacy; not a SOC 2 report |
| Korean CSAP program and applicable notice | conditional readiness questions for an in-scope cloud service; no certification, tier, or public-sector eligibility claim |

## Alignment and certification limits

Reference alignment does not establish certification, formal conformance, or independent assurance.

- NIST publications and SLSA concepts are engineering guidance here. Their citation does not establish regulatory compliance, a SLSA level, or independent assurance.
- ISO/IEC/IEEE 42010, ISO/IEC/IEEE 29148, and ISO/IEC 25010 provide architecture, requirements, and quality-model baselines. Repository documentation may be aligned to their concepts, but no formal conformance assessment is claimed.
- ISO/IEC 27002 provides control guidance and cannot itself be certified. ISO/IEC 27001 or ISO/IEC 42001 certification would require a defined management-system scope, implemented controls, evidence over time, and an authorized independent certification process.
- ISO/IEC/IEEE 29119 alignment means that the test strategy uses compatible concepts and process concerns. No conformance assessment against either named part has been performed.
- SOC 2 is an attestation engagement using AICPA criteria. Repository tests and traceability can contribute evidence, but they are not a SOC 2 report and do not establish control design or operating effectiveness for a scoped service period.
- Korean CSAP evaluates an actual cloud service against applicable legal and program criteria. Eligibility, service type/tier, data location, isolation, operational controls, and the current governing notice must be resolved for the real deployment with KISA or an authorized assessor. Source-repository controls alone cannot establish CSAP readiness or certification.
- Where a cited draft and final publication coexist, the final publication is normative for this baseline and the draft is informative until its official status changes.

## APA 7 references

American Institute of Certified Public Accountants, Assurance Services Executive Committee. (2023). *2017 Trust Services Criteria for security, availability, processing integrity, confidentiality, and privacy (with revised points of focus—2022).* https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022

Booth, H., Ogata, M., Kent, K., Souppaya, M., & Dodson, D. (2025). *Secure software development framework (SSDF) version 1.2: Recommendations for mitigating the risk of software vulnerabilities* (Initial Public Draft, NIST Special Publication 800-218 Rev. 1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218r1.ipd

Chandramouli, R., Kautz, F., & Torres Arias, S. (2024). *Strategies for the integration of software supply chain security in DevSecOps CI/CD pipelines* (NIST Special Publication 800-204D). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-204D

GitHub. (n.d.). *About protected branches*. Retrieved August 9, 2026, from https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *OpenID Connect*. Retrieved August 9, 2026, from https://docs.github.com/en/actions/concepts/security/openid-connect

GitHub. (n.d.). *Reuse workflows*. Retrieved August 9, 2026, from https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows

GitHub. (n.d.). *Secure use reference*. Retrieved August 9, 2026, from https://docs.github.com/en/actions/reference/security/secure-use

International Organization for Standardization. (2022a). *Information security, cybersecurity and privacy protection—Information security controls* (ISO/IEC 27002:2022). https://www.iso.org/standard/75652.html

International Organization for Standardization. (2022b). *Information security, cybersecurity and privacy protection—Information security management systems—Requirements* (ISO/IEC 27001:2022). https://www.iso.org/standard/27001

International Organization for Standardization. (2023a). *Systems and software engineering—Systems and software Quality Requirements and Evaluation (SQuaRE)—Product quality model* (ISO/IEC 25010:2023). https://www.iso.org/standard/78176.html

International Organization for Standardization. (2023b). *Information technology—Artificial intelligence—Management system* (ISO/IEC 42001:2023). https://www.iso.org/standard/42001

International Organization for Standardization, International Electrotechnical Commission, & Institute of Electrical and Electronics Engineers. (2018). *Systems and software engineering—Life cycle processes—Requirements engineering* (ISO/IEC/IEEE 29148:2018). https://www.iso.org/standard/72089.html

International Organization for Standardization, International Electrotechnical Commission, & Institute of Electrical and Electronics Engineers. (2021). *Software and systems engineering—Software testing—Part 2: Test processes* (ISO/IEC/IEEE 29119-2:2021). https://www.iso.org/standard/79428.html

International Organization for Standardization, International Electrotechnical Commission, & Institute of Electrical and Electronics Engineers. (2022a). *Software and systems engineering—Software testing—Part 1: General concepts* (ISO/IEC/IEEE 29119-1:2022). https://www.iso.org/standard/81291.html

International Organization for Standardization, International Electrotechnical Commission, & Institute of Electrical and Electronics Engineers. (2022b). *Software, systems and enterprise—Architecture description* (ISO/IEC/IEEE 42010:2022). https://www.iso.org/standard/74393.html

International Organization for Standardization, International Electrotechnical Commission, & Institute of Electrical and Electronics Engineers. (2026). *Systems and software engineering—Life cycle processes—Requirements engineering* (ISO/IEC/IEEE DIS 29148, Edition 3, draft). https://www.iso.org/standard/94091.html

Kent, K., & Souppaya, M. (2006). *Guide to computer security log management* (NIST Special Publication 800-92). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-92

Korea Internet & Security Agency. (n.d.). *클라우드서비스 보안인증(CSAP).* Retrieved August 9, 2026, from https://www.kisa.or.kr/1050603

과학기술정보통신부. (2023). *클라우드컴퓨팅서비스 보안인증에 관한 고시* (과학기술정보통신부고시 제2023-4호). 국가법령정보센터. https://law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000218804

OpenTelemetry Authors. (2026). *OpenTelemetry specification 1.59.0*. https://opentelemetry.io/docs/specs/otel/

Open Source Security Foundation. (2026). *SLSA specification, version 1.2*. https://slsa.dev/spec/v1.2/

Scarfone, K., & Souppaya, M. (2023). *Cybersecurity log management planning guide* (Initial Public Draft, NIST Special Publication 800-92 Rev. 1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-92r1.ipd

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

## Review cadence

Re-check final/draft status and current versions at least quarterly and whenever a boundary-changing PR cites these sources. Replace a source only through an ADR/traceability update; do not silently change the normative baseline.