### GRC central quality workflow remains staged behind isolated runner admission

- Add the central `workflow_call` quality lane, thin-caller template, and
  regression contracts for GRC lint/tests/coverage while keeping product policy
  in `ContextualWisdomLab/governance-risk-compliance`.
- This is source preparation only. No consumer caller is installed, no runner
  access is expanded, and no hosted fallback is introduced. Activation still
  requires the authorized disposable isolated-runner and cleanup canary,
  exact-head required Checks, independent approval, and ordinary protected
  integration.
