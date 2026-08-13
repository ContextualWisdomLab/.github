# CodeQL action single-version pin

## Incident and buyer impact

Dependabot opened separate pull requests for `codeql-action/init` and
`codeql-action/upload-sarif`. If those land on different SHAs, the PR
analyzer and the scheduled SARIF uploader execute different trusted
action code. A buyer cannot treat a green CodeQL gate as evidence that
the scheduled scan used the same reviewed binary.

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Pin `init`, `analyze`, and `upload-sarif` to one immutable SHA
(`5595ccaf912efad79be6eef63a5619ff05969be3`, v4.37.6) in both
`codeql-pr.yml` and `scheduled-security-scan.yml`. Contract tests reject
per-file and cross-workflow splits.

CWE-829 forbids including functionality from an untrusted or unreviewed
control sphere (MITRE, 2026). A second SHA is a second control sphere.

## References

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

GitHub. (n.d.). *Using the CodeQL action*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/code-security/code-scanning/creating-an-advanced-setup-for-code-scanning/using-the-codeql-action
