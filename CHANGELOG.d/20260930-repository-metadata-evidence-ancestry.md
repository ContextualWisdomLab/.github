### Repository metadata validation receives published evidence ancestry

- The Repository Metadata Reconcile validation job now fetches complete Git
  history before the repository-wide contract suite checks whether documented
  evidence commits belong to the current exact-head ancestry. Exact revision
  verification and credential isolation remain unchanged.
