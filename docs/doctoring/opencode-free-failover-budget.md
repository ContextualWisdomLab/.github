# OpenCode free-tier failover budget

## Incident and buyer impact

Materialize accepts only exact SHA-256 pins or a bounded relative `-r`
include; a lone `--require-hashes` line is not lock evidence.

A stale free alias (`ling-3.0-flash-free` and five ungoverned catalog names)
could occupy the central review pool for 3600 seconds and exhaust the step
without a verdict. Paid NVIDIA NIM and GitHub Models candidates never ran.
Review evidence then looked as if the lab had no LLM review.

## Decision

Keep the seven governed free candidates. Bound
`OPENCODE_FREE_RUN_TIMEOUT_SECONDS` to 300. Leave the 5400-second paid/large
review budget and the 180/900-second NVIDIA NIM caps unchanged. A free-tier
timeout only advances the pool; it cannot approve. This allocates remaining
test-time compute to the deep paid/NIM path rather than a dead free worker.
Speed is not the success metric; completing a real review is.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5
