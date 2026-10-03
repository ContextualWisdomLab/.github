## Fixed

- OpenCode reviews no longer fail before running after a self-hosted runner's
  temp directory is cleaned. The trusted checkout outlives jobs and still
  registered the removed pull-request-head worktree; it is now pruned before
  the worktree is recreated.
