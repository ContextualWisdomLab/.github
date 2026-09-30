### Fixed

- Install hash-pinned PyYAML in the central quality environment so workflow
  contract tests can be collected instead of failing before coverage.
- Install the hash-pinned Noema document toolchain in the full Agent Mention
  Router quality gate, including its `defusedxml` collection dependency.
- Refresh vulnerable Noema reader and Cargo coverage-fixture locks to
  `fast-uri` 3.1.8, `ip-address` 10.7.2, and PyO3 0.29.3.
