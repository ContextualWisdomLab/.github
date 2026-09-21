### Noema re-dispatches an all-429 sidecar preflight as provider capacity

- `.github/workflows/noema-review.yml` gives the sidecar provision step `id: sidecar` and adds
  `Classify all-429 sidecar preflight as provider capacity`. When that step fails, the new step runs
  `scripts/ci/noema_preflight_capacity.py` on `strix_runs/contextual-orchestrator-preflight.json`.
  If every probed route was refused with HTTP 429 and none is ready, it emits the same ADR-0031
  transport outputs that `noema_prepare` emits. `Schedule bounded Noema transport re-dispatch` now
  accepts either source, with the same attempt counter, bound, delay function, and live-head check.
  Any other preflight evidence keeps the plain failure. The job still fails and review remains
  required. Strix is a follow-up. Refs #2148.
