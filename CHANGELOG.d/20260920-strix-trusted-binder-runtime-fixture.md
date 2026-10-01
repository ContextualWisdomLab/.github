### Strix keeps trusted evidence binding outside consumer workspaces

- The Strix gate resolves its evidence binder beside the trusted gate source.
  The executable core harness now materializes that trusted runtime under a
  separate source directory, passes a binder-free consumer workspace through
  `STRIX_REPO_ROOT`, and invokes the trusted gate by its absolute path.
- OpenCode coverage assertions follow the consolidated
  `validate-pr-metadata` owner instead of the removed
  `coverage-source-tree` job and failure-report step.
- The commercial-readiness receipt contract now compares the complete parsed
  harden-runner endpoint set instead of treating an expected hostname as a URL
  substring. This closes the exact CodeQL
  `py/incomplete-url-substring-sanitization` finding without suppressing it or
  widening egress.
- The branch adopts the current central dependency owner, including the
  explicit AnyIO 4.14.2 source-to-hash pin required by the Python security
  gate.
- The package-description reusable workflow now isolates arbitrary caller build
  backends in an artifact producer job. A fresh inspector job receives only the
  staged distribution or README, checks out the exact central workflow source,
  and runs the gate with Python isolated mode, so caller code cannot rewrite the
  trusted gate or poison its interpreter before a GREEN verdict.
