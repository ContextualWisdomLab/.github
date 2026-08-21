# OSV direct-source provenance reconciliation

## Decision

The central Security Scan preserves OSV Scanner as the hard base/head
vulnerability gate. It adds a narrow evidence reconciliation step for pnpm
dependencies whose lock entry proves an exact immutable non-registry source.
The first governed source is the official SheetJS CE HTTPS release artifact.

A registry advisory is removed from the reporter input only when all of these
facts agree:

1. package name and strict three-component version;
2. the pnpm package key and `resolution.tarball` canonical HTTPS URL;
3. the official `cdn.sheetjs.com` origin and versioned release path;
4. one valid SHA-512 integrity receipt; and
5. an advisory-provided, machine-checkable exclusive affected upper bound that
   the exact artifact version is outside.

An affected version remains a finding. Missing integrity, an unknown host,
version disagreement, malformed JSON or an absent/ambiguous affected range is
retained and recorded as `SCANNER_METADATA_CONFLICT`. No advisory identifier,
package name, or severity is blanket-ignored. The audit artifact records every
retained or reconciled direct-source decision without copying untrusted
advisory prose.

## Empty result documents

The pinned OSV action can complete successfully without creating its requested
JSON file when a repository has no findings or no supported lockfile. The
central workflow first requires both base and head scans to report success,
then writes the valid empty document `{"results":[]}` for any missing or empty
result file. A failed first scan and failed retry never enter this path, and
symlinked result paths remain a hard failure. This preserves the distinction
between a verified clean scan and an unavailable scan without weakening the
base/head reporter gate.

## Rollback and operations

Rollback removes the reconciliation step and helper together, restoring raw
OSV reporter inputs. Operators should inspect `osv-provenance-audit.json`
alongside `old-results.json`, `new-results.json`, and `results.sarif`. A metadata
conflict is non-passing when the underlying OSV finding is new because the
finding remains in the reporter input.

## References

Google. (2026). *OSV-Scanner documentation*. Open Source Vulnerabilities.
https://google.github.io/osv-scanner/

OpenSSF. (2025). *Open source vulnerability format specification*. Open Source
Security Foundation. https://ossf.github.io/osv-schema/

pnpm. (2026). *Settings: Lockfile*. https://pnpm.io/settings#lockfile

SheetJS LLC. (2026). *SheetJS Community Edition*. https://docs.sheetjs.com/
