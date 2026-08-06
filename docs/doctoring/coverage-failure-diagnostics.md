# Credential-redacted coverage failure diagnostics

## Decision

Coverage setup failures are security-relevant review evidence, but exception text is untrusted and may contain registry URL userinfo, authorization headers, API tokens, database connection strings, passwords, or encryption keys. JavaScript and Python trusted-lock materializers therefore delegate multiline `GITHUB_OUTPUT` publication to one shared helper. The helper normalizes whitespace, applies the central credential sanitizer, bounds each field, HTML-escapes Markdown-embedded evidence, and replaces the fixed multiline delimiter before publication.

The sanitizer applies URL-userinfo and complete authorization-header-value redaction before key-value truncation so mixed single-line failures cannot preserve an earlier credential. It deliberately does not enumerate authentication schemes: `Bearer`, `Basic`, `Token`, `Digest`, AWS signing schemes, custom provider schemes, and scheme-less values are all untrusted and replaced in full after the `Authorization` field separator. The final output retains the failure class, stage, bounded non-secret context, and remediation without exposing raw credentials. Local CLI status remains nonzero when publication is unavailable.

## Type-only TypeScript coverage boundary

The changed-source JavaScript/TypeScript gate must distinguish executable code from declarations that TypeScript removes before JavaScript execution. A type-only source file can therefore be legitimately absent from Istanbul's `coverage-final.json`; treating that absence alone as uncovered runtime code creates a false merge blocker even when every production statement and branch is covered.

The gate now checks an omitted changed file before failing. It permits the omission only when every changed line is conservatively classified as a comment, delimiter, multiline `import type` statement, or line within a balanced `interface` declaration. TypeScript documents that `import type` is fully erased and that type annotations and other type-system constructs are removed when JavaScript is emitted. Unsupported declaration syntax, malformed or unbalanced structures, ordinary imports, values, functions, classes, object literals, and any other runtime-looking line remain fail-closed and still require matching Istanbul evidence.

This is not a filename exemption. A file named `types.ts` receives no special trust, and a mixed declaration/runtime file continues to fail when any changed executable-looking line lacks instrumentation. The classifier also strips quoted string literals only for interface brace counting; it does not execute a TypeScript parser, infer semantics, or convert a failed coverage result into success.

## Verification contract

The exact-head gate requires Python 3.10 compilation, Python 3.14 tests, 100% production statement and branch coverage, 100% production docstrings, and direct execution of the shared sanitizer CLI contract. Regression cases cover mixed URL, arbitrary Authorization schemes, scheme-less Authorization values, token secrets, delimiter injection, oversized errors, missing `GITHUB_OUTPUT`, and both materializer call paths. Temporary write-capable repair workflows are removed from the final tree.

The type-only regression reproduces the Inkspan review failure with an empty Istanbul final map, a multiline type-only import, an exported interface, interface-local documentation, and a newly added interface property. It must pass only because no changed executable unit exists. Existing tests preserve the opposite boundary: a changed runtime source absent from instrumentation fails with the file name, and a runtime-looking line with no mapped Istanbul unit fails closed.

### Test-first evidence

- Inkspan exact-head review failure: central OpenCode review-dispatch run `31092356765` reported `src/types.ts` absent from `coverage-final.json` even though the changed file contained only type imports, public documentation, and interface properties.
- RED regression commit: `fcd16958aaed94336a222cefdf78c68d7f39a099`; trusted full-quality run `31096345623` failed on the new omitted-type-only fixture.
- Production repair commit: `3d4b82ebb6c50a0da54a19700f11b2724fd04c81`; the first full-quality run `31096849845` proved all 918 tests passed and identified one uncovered classifier branch rather than weakening the 100% branch gate.
- Branch-completion regression commit: `b39dfe533128e96be41e7db60d5eefb3f6cf311f`; the fixture adds interface-local documentation to exercise the conservative block-comment path.

Exact-head run identifiers after documentation integration belong in the pull-request release evidence; predecessor-head success is never sufficient for merge.

## Standards and guidance

GitHub environment files define delimiter-based multiline outputs and warn that a delimiter must not occur alone within arbitrary values. This implementation delimiter-proofs bounded fields before writing `GITHUB_OUTPUT`. OWASP logging guidance recommends removing, masking, sanitizing, hashing, or encrypting access tokens, passwords, database connection strings, encryption keys, session identifiers, and sensitive personal data rather than recording them directly. RFC 3986 deprecates secret passwords in URI userinfo because URIs are commonly displayed, stored, and logged.

TypeScript's official documentation defines type-only imports as declarations that are removed from emitted JavaScript and describes TypeScript's type system as erased during compilation. That primary technical contract supports a declaration-aware coverage decision, while the local conservative classifier and negative tests preserve fail-closed behavior for syntax outside the explicitly verified subset.

## Limitations

Pattern-based redaction is a defense-in-depth boundary, not a general secret classifier. Callers must not intentionally place secrets in exception messages. GitHub log masking and least-privilege workflow permissions remain required. The diagnostic helper does not make untrusted test output safe for shell evaluation or workflow-command execution.

The TypeScript classifier is intentionally not a complete parser. It does not exempt type aliases spanning arbitrary expressions, namespaces, enums, decorators, declaration merging, ambient modules, or newer syntax merely because those constructs may be erased in a particular toolchain. Expanding the accepted subset requires a failing fixture, authoritative compiler documentation, negative mixed-runtime tests, complete production statement and branch coverage, and exact-head review evidence.

## References

Berners-Lee, T., Fielding, R., & Masinter, L. (2005). *Uniform resource identifier (URI): Generic syntax* (RFC 3986). Internet Engineering Task Force. https://doi.org/10.17487/RFC3986

GitHub. (2026). *Workflow commands for GitHub Actions*. GitHub Docs. Retrieved August 5, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands

Microsoft. (n.d.). *TypeScript 3.8: Type-only imports and export*. TypeScript. Retrieved August 6, 2026, from https://www.typescriptlang.org/docs/handbook/release-notes/typescript-3-8.html

Microsoft. (n.d.). *TypeScript for the new programmer*. TypeScript. Retrieved August 6, 2026, from https://www.typescriptlang.org/docs/handbook/typescript-from-scratch.html

Microsoft. (n.d.). *Modules: Reference*. TypeScript. Retrieved August 6, 2026, from https://www.typescriptlang.org/docs/handbook/modules/reference.html

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
