## Fixed

- A completed Strix PR scan whose report names the scanned PR-scope
  directory that contains a changed file (for example
  `/workspace/strix-pr-scope.<id>/crates/core`) now counts as scoped. Such
  reports were rejected with "scan report does not identify a changed source
  file" even when they described the changed code. The scope root itself and
  unrelated directories still do not count.
