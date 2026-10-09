# Tool closure prepare before credentials

The unpushed prescreen candidate on `codex/pr2347-tooldeps-prescreen-20260924`
never became a pull request. Its licence-stage installer for the pinned
contextual-orchestrator lock stays unwired. `recognize_license_text` accepts
only reviewed whole texts, and
`.github/workflows/release-dependency-license-strix-gate.yml` already records
that judging the scanner's own closure is an owner decision. Calling
`tool-environment` from every review sidecar would fail closed after merge.

What this change does enforce:

- `tool-identity` refuses a symlinked checkout, a non-exact commit, a dirty
  tree, or a lock that is not a hash pin.
- Review, autofix, and release workflows run
  `contextual_orchestrator_review_sidecar.sh --prepare` with no provider
  secret, then launch with secrets. Launch refuses a missing or changed
  receipt and does not clone or install again.
- `install_gated` passes `--no-deps`, so the judged release closure cannot
  be re-resolved.
- `tool-environment` still runs the licence stage for a synthetic closure and
  is covered by `tests/test_release_dependency_tool_environment.py`. It is
  not a review-workflow caller.

The live pin checked while writing this note was
`01bf92a3ec67a0e1f9b68978eb16b60301e985fd`. Its `requirements.lock` is a
hash-pinned uv lock, not the older direct fast-mlsirm archive.
