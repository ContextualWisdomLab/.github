# Strix scan working-directory boundary

## Problem

The organization Strix gate bounded pull-request scans to a temporary scope,
but launched Strix with that scope as its current working directory. Strix
could therefore create `strix_runs/` and state files inside the tree it was
scanning. A self-generated state file was reported as a critical hard-coded
credential in a current-head `pg-erd-cloud` scan, while another scan reported a
missing unchanged DSN guard because the bounded scope omitted an imported
security helper.

## Decision

The gate now passes the canonical target directory as Strix's absolute `-t`
argument and runs the process from a fresh runner-temporary directory outside
the target. The temporary `strix_runs/` output is copied into the existing
active report directory after each attempt, so report classification and
artifact publication retain their previous evidence contract. The target is
never inferred from the working directory.

When a changed backend Python file belongs to a repository that contains
`backend/app/pg_introspect`, the bounded scope includes the package's available
trusted base helpers, including `dsn_guard.py` and `introspect.py`. Repositories
without that package are unchanged.

The bounded scope itself is created below the gate's private runtime directory.
The gate therefore owns the scope lifetime and an unrelated temporary-file
cleanup cannot remove scan input during PR-head blob materialization.

## Verification and rollback

`scripts/ci/test_strix_quick_gate.sh` verifies both the absolute target and the
outside working directory. It also verifies that a PostgreSQL DSN guard is
available to a scoped introspection scan. Run the shell syntax check and the
Strix quick-gate harness before publishing a central workflow change. Rollback
is a normal revert of the central PR; do not suppress changed-file attribution
or ignore scanner output to make a check green.

The fix addresses the trust boundary between untrusted scan input and scanner
output. It does not replace exact-head review, vulnerability remediation, or
the required security workflow.

## References

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

MITRE. (n.d.). *CWE-22: Improper limitation of a pathname to a restricted
directory ('Path traversal')*. Common Weakness Enumeration.
https://cwe.mitre.org/data/definitions/22.html

MITRE. (n.d.). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*.
Common Weakness Enumeration. https://cwe.mitre.org/data/definitions/367.html
