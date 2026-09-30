# Source repair claim and publication boundary

## Verified defects on PR #2174

The old dispatcher queued mutation before storing its exact-comment-revision
receipt. If the receipt failed, a later sweep could create a new envelope after
the worker changed the head and replay the same human command. Exact-head
revalidation alone did not prevent that new-envelope replay.

The worker checked changed paths before Python compilation. Compilation wrote
unsealed bytecode into repositories without ignore rules, and the final
`git add -A` had no staged-path check. An executed hostile fixture additionally
proved that a tracked PR-owned `py_compile.py` could shadow the standard module
when compilation ran from the target workspace.

## Minimal repairs

- Store the durable claim before dispatch. A failed claim propagates and queues
  no worker. A failed dispatch leaves the claim stored; operator inspection and
  a new explicit command are required rather than automatic replay.
- Compile with isolated Python (`-I`) and an explicit `-X pycache_prefix` under
  runner temporary storage. PR modules cannot replace the standard compiler,
  and bytecode is not added to the target repository.
- After staging, require every cached path to match the existing sealed NUL
  list before commit/push. No force push, approval or authority expansion.

## Executed evidence

Claim-order RED: two failures, demonstrating dispatch without a durable claim
and swallowed claim failure. Worker-shell RED: three failures plus one permitted
staging pass, demonstrating workspace bytecode, PR module execution and late
unsealed staging. The tests run the actual extracted workflow shell in a real
repository with no ignore rules; they do not only match prose or shell strings.

GREEN: 82 owned tests passed; 57 passed with `GITHUB_ACTIONS=true`. Both owned
production scripts retain 100% statement/branch coverage (398 statements,
148 branches) and 100% docstrings. A stored-claim/failed-dispatch regression also
proves that advancing the head does not replay the same command revision.

On code head `c0733dde27e7fc02496ec2381bc1f9ac1b59192d`, the full repository
suite completed with 5,246 passed, five skipped, 40 subtests passed in 433.42
seconds. The original log records `exit_code=0`; an inherited synthetic
HTTPError ResourceWarning remains visible and is not suppressed.

Fresh hosted current-head checks, independent review and protected integration
remain separate acceptance steps. Consumer opt-in
and live model-to-commit acceptance are not implied by these local repairs.
