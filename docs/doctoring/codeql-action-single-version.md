# CodeQL action single-version pin

## Incident and buyer impact

Dependabot opened an `upload-sarif` 4.37.6 bump while `codeql-pr.yml`
still ran `init`/`analyze` at 4.37.0 and `scheduled-security-scan.yml`
ran them at 4.37.5. A green upload does not prove the analyzer executed
the reviewed action.

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Pin every `github/codeql-action/{init,analyze,upload-sarif}` use to
`5595ccaf912efad79be6eef63a5619ff05969be3` (v4.37.6). Contract tests
reject per-file and org-wide splits.

CWE-829 forbids including functionality from an untrusted or unreviewed
control sphere (MITRE, 2026). A second SHA is a second control sphere.

## References

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

GitHub. (n.d.). *Using the CodeQL action*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/code-security/code-scanning/creating-an-advanced-setup-for-code-scanning/using-the-codeql-action
