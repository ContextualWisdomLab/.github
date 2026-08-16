# Production Stub Eradication — Research and Standards Traceability

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

## Decision summary

A success-shaped demo response in a production route is treated as a product and
security defect, not as harmless scaffolding. The organization gate therefore:

1. inventories every tracked runtime source file rather than only changed files;
2. distinguishes declaration contracts from executable placeholders;
3. fails closed on explicit production mock/stub paths;
4. preserves exact repository, default-branch commit, and central workflow
   provenance inside every `cwl.implementation-completeness/v2` artifact;
5. scans one stable twelfth every hour at minute 17, at most 12 repositories
   per invocation with `max-parallel: 4`, and uses deterministic continuation
   windows when a shard or full-fleet replay exceeds that cap;
6. creates one bounded, durable remediation issue per affected repository when
   that repository supports Issues; and
7. preserves the failed exact-SHA inventory artifact without an impossible issue
   mutation when Issues are disabled, closing an existing remediation issue only
   after an exact default-branch rescan is clean and the artifact is valid v2
   JSON with an empty finding and error set.

The twelve-way sharded cadence is an operational load boundary, not a relaxation
of finding semantics. SHA-256 assigns each repository to a stable shard; the
epoch-hour selects one shard. Each invocation then applies a preventive
12-repository window so worst-case scan time stays inside the hourly budget
(`ceil(12/4) * 20` minutes). Deferred repositories are visited on later
scheduled rounds or through full-fleet repository-dispatch
`continuation_offset`. Every finding still produces a nonzero scan result. This
reduces scheduled runner pressure while organization queue-starvation work
remains tracked separately and preserves exact-SHA evidence for acquisition and
security review.

This implements the NIST Secure Software Development Framework's outcome-based
expectation to identify and address root causes of software vulnerabilities and
uses ISO/IEC 25010:2023 as the product-quality frame for functional suitability,
reliability, security, maintainability, and testable acceptance criteria.
CWE-489 records leftover debug or demo code as a defect that can remain
reachable in production (MITRE Corporation, n.d.). The scanner treats those
executable placeholders as fail-closed inventory, not as optional style.
SSDF PW.4 requires archive and protect of each software release; the v2
inventory therefore carries `repository`, `repository_sha`, and `workflow_sha`
so an acquirer can bind the artifact to the exact default-branch commit and the
immutable central scanner revision (Souppaya et al., 2022).

NIST SP 800-218 Version 1.1 remains the final normative SSDF baseline. NIST SP
800-218 Revision 1 / SSDF Version 1.2 was an initial public draft as of December
2025 and is tracked as a future update rather than represented as final guidance.

## Evidence-to-control mapping

| Source concept | CWL control |
| --- | --- |
| Secure development practices must be integrated into the SDLC | Central hourly sharded scanner plus pull-request quality gates |
| Root causes should be addressed to prevent recurrence | Replace the stub and add a regression; do not merely suppress the finding |
| Acquirers need a common evidence vocabulary | Stable JSON schema `cwl.implementation-completeness/v2` with repository, commit, and workflow SHA fields |
| Product quality must be specified, measured, and evaluated | Exact-head inventory, tests, coverage, docstrings, CHANGELOG, operator evidence |
| Quality evaluation must span the lifecycle | Hourly stable-shard default-branch rescan, explicit full-fleet replay, and remediation evidence lifecycle |
| Operational controls must not create a competing availability defect | Twelve-way shard assignment, 12-repository preventive cap, four-way parallelism, and continuation receipts |

## APA 7th references

International Organization for Standardization, & International Electrotechnical
Commission. (2023). *Systems and software engineering—Systems and software
Quality Requirements and Evaluation (SQuaRE)—Product quality model*
(ISO/IEC Standard No. 25010:2023).
https://www.iso.org/standard/78176.html

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

MITRE Corporation. (n.d.). *CWE-489: Active debug code*. CWE. Retrieved
August 16, 2026, from https://cwe.mitre.org/data/definitions/489.html

National Institute of Standards and Technology. (2025, December 17). *Secure
Software Development Framework (SSDF) version 1.2 is available for public
comment*. https://www.nist.gov/news-events/news/2025/12/secure-software-development-framework-ssdf-version-12-available-public
