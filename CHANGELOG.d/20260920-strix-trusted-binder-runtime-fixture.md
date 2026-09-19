### Strix isolated-consumer tests materialize the trusted evidence binder

- The Strix gate now keeps its evidence binder rooted beside the trusted gate
  source while the executable test harness copies that binder into each
  isolated consumer fixture. The same contract also follows the consolidated
  `validate-pr-metadata` coverage owner instead of requiring the removed
  `coverage-source-tree` job and failure-report step.
