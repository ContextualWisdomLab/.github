## Fixed

- Coverage jobs also remove run-numbered coverage workspaces older than two
  hours. The sandbox writes them as root, so the runner's own temp cleanup
  could not, and they refilled the self-hosted runner's disk. Shared coverage
  directories are never removed.
