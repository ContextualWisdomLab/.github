### Sidecar provisioning names a full runner disk

- `scripts/ci/contextual_orchestrator_review_sidecar.sh` now checks free space under `RUNNER_TEMP`
  before cloning or building the sidecar venv and warns below 2 GiB and stops with a "runner disk" error below 512 MiB. On
  2026-09-29 a full cwlab-s1-04 disk surfaced as venv/pip failures that read like a provider outage.
