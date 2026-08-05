# Strix source-directory boundary

## Decision

`STRIX_SOURCE_DIRS` is a scanner input boundary, not an arbitrary filesystem path list. The central Strix gate now accepts only `.` or direct child directory names whose characters are drawn from a known-good Unicode-aware allowlist. The normalized value is deduplicated, bounded to 32 entries and 8,192 input bytes, and frozen as a read-only shell variable before any path join occurs.

Nested paths are intentionally not accepted. The gate already resolves and validates `STRIX_TARGET_PATH`; callers that need a nested scan root must select that root through the target-path contract and use `STRIX_SOURCE_DIRS=.`. This keeps one canonical trust boundary instead of composing two independently mutable path fragments.

## Threat model

Before this change, each whitespace-delimited `STRIX_SOURCE_DIRS` token was appended to the canonical target root. A caller-controlled absolute path could discard the intended root, while `..` components or nested symlink chains could resolve outside it. The subsequent recursive search could then read unrelated runner files and allow their content to influence a published Strix report.

The protected boundary rejects:

- absolute paths;
- `/` and `\\` separators;
- parent traversal and nested path components;
- shell glob and metacharacter input;
- option-like names beginning with `-`;
- control characters, tabs, and line breaks;
- overlong components, overlong lists, and excessive entry counts.

Safe direct names remain internationalized: Unicode letters, combining marks, and numbers are accepted. The final candidate must still be a real non-symlink directory under the already-canonical scan target before recursive search begins.

## Verification

`tests/test_strix_model_utils_source_dirs.py` provides executable regressions for:

- deterministic deduplication and order preservation;
- Korean direct-directory names;
- read-only post-validation state;
- relative and absolute traversal;
- nested paths and both path separators;
- glob, punctuation, option-like, control-character, size, and cardinality limits.

The test was first executed against the prior helper and failed for traversal, absolute, nested, glob, punctuation, and duplicate inputs. It passes after the source-boundary contract is installed. The helper is also parsed with `bash -n`, and the Python regression module is compiled before publication.

## Security properties and limits

The change follows an accept-known-good strategy instead of attempting to remove dangerous substrings. It also avoids returning the rejected value in error messages. This prevents the common failure mode where filtering one traversal representation leaves another representation or where diagnostics disclose useful filesystem details.

This control does not make arbitrary scanner output trustworthy. Strix findings remain untrusted data, provider failures remain fail-closed, PR-head materialization remains bounded to validated Git objects, and privileged workflow publication continues to require exact-head checks and repository protection.

## References

MITRE. (2026, April 30). *CWE-22: Improper limitation of a pathname to a restricted directory ('path traversal')* (Version 4.20). Common Weakness Enumeration. https://cwe.mitre.org/data/definitions/22.html

OWASP Foundation. (n.d.). *Path traversal*. Retrieved August 5, 2026, from https://owasp.org/www-community/attacks/Path_Traversal
