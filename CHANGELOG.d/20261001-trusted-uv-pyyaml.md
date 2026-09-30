### Fixed

- Install hash-pinned PyYAML in the central quality environment so workflow
  contract tests can be collected instead of failing before coverage.
- Install the hash-pinned Noema document toolchain in the full Agent Mention
  Router quality gate, including its `defusedxml` collection dependency.
- Refresh vulnerable Noema reader and Cargo coverage-fixture locks to
  `fast-uri` 3.1.8, `ip-address` 10.7.2, and PyO3 0.29.3.
- Pin and regenerate the pip-audit and Strix locks with urllib3 2.8.0 and
  PyJWT 2.15.1 after exact-head Python Security findings and the subsequent
  recursion-hardening release.
- Fetch complete Git comparison history in the Trusted uv full-suite gate so
  published-lineage contracts can resolve current-HEAD ancestors, and restore
  the baseline's required APA 7th reference section.
- Install the hash-pinned Noema document toolchain in Repository Metadata
  Reconcile before its repository-wide pytest step, preventing `defusedxml`
  collection failures after the coverage prerequisite merge.
- Pin LiteLLM 1.94.3 in the Strix source and regenerated hash lock after
  Python Security found CVE-2026-84377 credential exfiltration and SSRF in
  1.94.1.
