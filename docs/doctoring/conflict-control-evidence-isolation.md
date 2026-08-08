# Conflict-Control Evidence Isolation

## Decision

The OpenCode-assisted ordinary and merge-conflict repair worker treats its
pre-model worktree snapshot and exact-path allowlist as **security control-plane
evidence**, not as ordinary pull-request data. Both paths must be located outside
the model-writable repository worktree. The verifier checks both the caller-visible
absolute path and the canonical resolved target so a path inside the worktree, or
an outside-looking symbolic link that resolves back into it, fails closed before
it can authorize or verify a model write.

The snapshot writer applies the same rule before creating its output. This keeps
the model from changing the evidence that later decides whether its own writes
are permitted. The production workflow already places these files under
`RUNNER_TEMP`; the helper now enforces that trust boundary instead of merely
assuming the caller preserves it.

## Threat model and rationale

A write-capable repair model operates on an untrusted pull-request worktree.
Allowing either authoritative control file to reside in that worktree creates a
self-reference: the model could modify the allowlist or snapshot and then be
judged against evidence it helped alter. That violates the existing separation
between untrusted repository state and trusted workflow state.

MITRE CWE-22 describes path-validation failures in which pathname handling lets
a resource resolve outside its intended restricted location. The direction here
is inverted—the security requirement is that trusted control evidence resolve
**outside** the untrusted worktree—but the same canonical-path principle applies:
security decisions must be made against the path's effective resolved location,
not only its textual spelling. GitHub likewise requires privileged Actions
workflows to treat pull-request-controlled content as untrusted and recommends
strong separation when privileged workflows process such content.

The invariant is intentionally simple and auditable:

1. canonicalize and validate the repository root;
2. obtain the control file's absolute path;
3. resolve existing symbolic-link components without requiring a not-yet-created
   snapshot output to exist;
4. reject if either representation is the repository root or one of its
   descendants; and
5. only then read or write the control file.

No repository path is added to an allowlist to work around this rule. No failed
security result is reclassified as infrastructure noise simply because later
provider attempts are rate-limited or unavailable.

## Test-first evidence

Strix Security Scan on predecessor exact head
`8ab55aa29ce41aafe5f0f5c4195c7726861bf518` reported a HIGH finding that the
snapshot and allowlist placement was assumed rather than enforced. The finding
remained valid even though later scanning attempts encountered provider failures.

Permanent RED contracts were committed first at
`b2dedc049011900590b4cb3246f77cc438468148`. They require:

- snapshot output inside the repository to fail before creation;
- either verification input inside the repository to fail closed; and
- an outside-looking symbolic link resolving into the repository to fail closed.

Production enforcement followed at
`fef1a348973dc8b402127fc7765251aa6594327f`. These commit identifiers are
historical TDD evidence only. Merge acceptance still requires the exact current
head to pass every required security, CI, coverage, review, and branch-protection
gate.

## Operational contract

The trusted workflow should continue to place snapshot and allowlist files under
`RUNNER_TEMP` while the target pull-request checkout remains under its separate
workspace directory. If an operator changes those paths so either control file
lands in the target worktree, the job is expected to stop rather than repair the
pull request.

This control complements, rather than replaces, the existing defenses: complete
tracked/untracked/ignored worktree snapshots, exact-path allowlists, symlink
validation, `.git` edit denial, hook suppression, explicit push destinations,
exact-head revalidation, independent review, and protected merge policy.

## Rollback

A rollback must revert the control-path tests, helper enforcement, this doctoring
record, and changelog together. Reverting only the enforcement while retaining a
workflow that assumes `RUNNER_TEMP` is sufficient would reopen the reported trust
boundary. A rollback is never permission to accept a failed or stale security
scan.

## References

GitHub, Inc. (n.d.-a). *Secure use reference*. GitHub Docs. Retrieved August 8,
2026, from https://docs.github.com/en/actions/reference/security/secure-use

GitHub, Inc. (n.d.-b). *Script injections*. GitHub Docs. Retrieved August 8,
2026, from https://docs.github.com/en/actions/concepts/security/script-injections

MITRE Corporation. (2026, April 30). *CWE-22: Improper limitation of a pathname
to a restricted directory ('Path Traversal') (Version 4.20)*. Common Weakness
Enumeration. https://cwe.mitre.org/data/definitions/22.html
