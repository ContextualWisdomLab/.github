# Credential-redacted coverage failure diagnostics

## Decision

Coverage setup failures are security-relevant review evidence, but exception text is untrusted and may contain registry URL userinfo, authorization headers, API tokens, database connection strings, passwords, or encryption keys. JavaScript and Python trusted-lock materializers therefore delegate multiline `GITHUB_OUTPUT` publication to one shared helper. The helper normalizes whitespace, applies the central credential sanitizer, bounds each field, HTML-escapes Markdown-embedded evidence, and replaces the fixed multiline delimiter before publication.

The sanitizer applies URL-userinfo and complete authorization-header-value redaction before key-value truncation so mixed single-line failures cannot preserve an earlier credential. It deliberately does not enumerate authentication schemes: `Bearer`, `Basic`, `Token`, `Digest`, AWS signing schemes, custom provider schemes, and scheme-less values are all untrusted and replaced in full after the `Authorization` field separator. The final output retains the failure class, stage, bounded non-secret context, and remediation without exposing raw credentials. Local CLI status remains nonzero when publication is unavailable.

## Verification contract

The exact-head gate requires Python 3.10 compilation, Python 3.14 tests, 100% production statement and branch coverage, 100% production docstrings, and direct execution of the shared sanitizer CLI contract. Regression cases cover mixed URL, arbitrary Authorization schemes, scheme-less Authorization values, token secrets, delimiter injection, oversized errors, missing `GITHUB_OUTPUT`, and both materializer call paths. Temporary write-capable repair workflows are removed from the final tree.

## Standards and guidance

GitHub environment files define delimiter-based multiline outputs and warn that a delimiter must not occur alone within arbitrary values. This implementation delimiter-proofs bounded fields before writing `GITHUB_OUTPUT`. OWASP logging guidance recommends removing, masking, sanitizing, hashing, or encrypting access tokens, passwords, database connection strings, encryption keys, session identifiers, and sensitive personal data rather than recording them directly. RFC 3986 deprecates secret passwords in URI userinfo because URIs are commonly displayed, stored, and logged.

## Limitations

Pattern-based redaction is a defense-in-depth boundary, not a general secret classifier. Callers must not intentionally place secrets in exception messages. GitHub log masking and least-privilege workflow permissions remain required. The diagnostic helper does not make untrusted test output safe for shell evaluation or workflow-command execution.

## References

Berners-Lee, T., Fielding, R., & Masinter, L. (2005). *Uniform resource identifier (URI): Generic syntax* (RFC 3986). Internet Engineering Task Force. https://doi.org/10.17487/RFC3986

GitHub. (2026). *Workflow commands for GitHub Actions*. GitHub Docs. Retrieved August 5, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
