### Strix keeps trusted evidence binding outside consumer workspaces

- The Strix gate resolves its evidence binder beside the trusted gate source.
  The executable core harness now materializes that trusted runtime under a
  separate source directory, passes a binder-free consumer workspace through
  `STRIX_REPO_ROOT`, and invokes the trusted gate by its absolute path.
- OpenCode coverage assertions follow the consolidated
  `validate-pr-metadata` owner instead of the removed
  `coverage-source-tree` job and failure-report step.
