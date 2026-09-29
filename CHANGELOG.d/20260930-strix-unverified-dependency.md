## Changed

- The Strix gate no longer fails closed on a finding that names only packages
  the repository does not depend on. When such a finding has no file location,
  every package in its Target, Package and Introduced By fields is absent from
  every dependency manifest and lockfile, and the pull request changes no
  manifest, the gate records it as unverified with a warning annotation. A
  model reported a lodash CVE (itself misattributed) on a Rust/Python
  repository with no JavaScript dependencies.
