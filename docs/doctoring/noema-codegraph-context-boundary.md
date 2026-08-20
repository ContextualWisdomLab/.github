# Noema CodeGraph Context Boundary

## Customer action

Keep `NOEMA_CODEGRAPH_CONTEXT_PATH` unset unless the review job has generated a
context file inside its checked-out workspace. When it is set, use a relative
regular-file path such as `.codegraph/review-context.md`; absolute paths,
`..` traversal, and symlinked components are rejected before any bytes are read.

## Root-cause record

The Noema reviewer accepted an environment-provided filename directly in
`load_codegraph_context()`. A review-job process that inherited an unintended
absolute or traversal path could therefore read files outside the repository.
This is CWE-22 path traversal: canonicalization must remain inside a restricted
parent, and error output must not disclose the rejected path.

The repair establishes one bounded trust boundary:

1. accept only a non-empty relative path without `..` components;
2. reject symlinks in every path component;
3. resolve the candidate and require it to remain below the current workspace;
4. require a regular file and read at most `MAX_REVIEW_CONTEXT_CHARS + 1` bytes;
5. return a generic diagnostic so the untrusted environment value is not echoed.

## Verification

The contract tests cover a valid workspace file, absolute traversal, relative
traversal, a symlink escape, bounded reads, and the existing review-context
assembly. The check is intentionally fail-closed: missing or invalid context
reduces evidence rather than expanding file access.

## Standards and authoritative references (APA 7th)

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53, Revision 5,
Update 1). National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (n.d.). *CWE-22: Improper limitation of a pathname to a restricted
directory ('Path traversal')* (Version 4.20). Common Weakness Enumeration.
Retrieved August 21, 2026, from https://cwe.mitre.org/data/definitions/22

OWASP Foundation. (n.d.). *Path traversal*. Retrieved August 21, 2026, from
https://owasp.org/www-community/attacks/Path_Traversal
