# OSV scanner version comments and Scorecard Token-Permissions

## Incident and buyer impact

Dependabot PR ContextualWisdomLab/.github#921 bumped
`google/osv-scanner-action/osv-scanner-action` to
`f4cfcc01edc9c8b756a9b873b7a623ca674da51e`, which embeds
`ghcr.io/google/osv-scanner-action:v2.5.0`. The four `uses:` comments
still said `# v2.3.8`. A one-shot repair workflow then granted
top-level `contents: write` so GitHub Actions could rewrite those
comments. OpenSSF Scorecard Token-Permissions scored that workflow 0,
and the repair job itself failed on an unterminated Python string.
A commercial buyer reading the security dashboard saw a red Scorecard
gate and could not tell which OSV scanner release actually ran.

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Correct the four trailing comments in-tree to `# v2.5.0`. Delete the
one-shot writer. Do not grant `contents: write` to repair a comment.
Keep the exact full SHA, scan arguments, reporter pin, timeouts, and
permissions unchanged. Temporary branch-writer workflows are not
merge evidence.

This is version-comment honesty and least-privilege token scope, not
operational-PII masking.

## References

National Institute of Standards and Technology. (2022). *Secure
software development framework (SSDF) version 1.1: Recommendations
for mitigating the risk of software vulnerabilities* (NIST Special
Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218

OpenSSF Scorecard. (2024). *Check: Token-Permissions*.
https://github.com/ossf/scorecard/blob/main/docs/checks.md#token-permissions

Supply-chain Levels for Software Artifacts. (2023). *SLSA v1.0
specification*. https://slsa.dev/spec/v1.0/

GitHub. (2025). *Automatic token authentication*.
https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication
