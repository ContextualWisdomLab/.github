## Fixed

- Rebuild the review sidecar's virtual environment on every run. On the
  OpenCode runner a damaged environment survived between jobs, so every later
  OpenCode review failed while installing its dependencies
  (`No module named pip.__main__`) and no verdict was published after
  2026-09-27.
