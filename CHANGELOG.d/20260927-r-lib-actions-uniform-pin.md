### Fixed

- Keep all five reusable R-package workflow actions on the same immutable
  `r-lib/actions` commit when adopting v2.13.0, preventing a partial
  Dependabot update from violating the workflow's uniform-pin contract.
