# Scorecard action single-version pin

## Incident and buyer impact

Dependabot bumps `ossf/scorecard-action` one workflow at a time. If the
PR visibility job and the default-branch analysis job execute different
SHAs, a green Scorecard gate does not prove the scheduled posture scan
used the reviewed action.

## Decision

Pin both `scorecard-pr.yml` and `scorecard-analysis.yml` to
`2d1146689b8cda280b9bc96326124645441f03bc` (v2.4.4). A contract test
rejects a split.

CWE-829 forbids including functionality from an untrusted or unreviewed
control sphere (MITRE, 2026). A second SHA is a second control sphere.

## References

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

OpenSSF. (n.d.). *Scorecard action*. GitHub. Retrieved August 13, 2026,
from https://github.com/ossf/scorecard-action
