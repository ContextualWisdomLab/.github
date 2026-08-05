# Trusted uv quality regression repair evidence

Exact head `d3b6c79aed988120ce70c08274d76127a04a0c41` failed the Python 3.14 complete quality gate because two tests had stale environmental assumptions.

The Git safety test depended on a private Git test hook producing a dubious-ownership failure. Git 2.54.0 on the hosted runner returned success. The repaired test now inspects the effective protected configuration directly and requires exactly one `safe.directory` entry equal to the validated worktree, with neither an unrelated repository nor a wildcard.

The Strix fallback test still supplied a retired model identifier after the reviewed policy changed the unrequested public default. The repaired test now supplies the current default and continues to prove that an unavailable default credential selects the established fallback.

One-shot workflow run `30976255239` completed successfully and removed itself. It passed both focused regressions, the complete central pytest suite under coverage, production docstring enforcement for `scripts/ci`, and Python compilation.

The repair changes test evidence only. It does not weaken trusted dependency materialization, provider selection, security scans, or the exact-head merge policy.
