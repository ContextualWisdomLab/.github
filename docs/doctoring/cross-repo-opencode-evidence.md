# Cross-repository OpenCode evidence

## Incident and buyer impact

Sibling-repo reviews (for example `ContextualWisdomLab/naruon#1317`) lost
coverage-evidence when the former Astral release endpoint rejected requests,
and the OpenCode App token could not publish a commit status across
repositories. A later Strix provider outage was also converted into a green
required check, so incomplete security evidence looked like a pass.

## Decision

1. Download uv from the literal GitHub Releases HTTPS URL with a fixed
   `User-Agent`, disable proxies, reject redirects, and retain size, checksum,
   and executable-version checks. Repository or user data cannot select the
   network origin.
2. Before skipping cross-repository status publication, prove an exact-head
   formal OpenCode review (`APPROVED` or `CHANGES_REQUESTED`). Missing proof
   fails closed.
3. Keep Strix red when the backend is unavailable. Incomplete provider
   evidence is not a clean scan.

## References

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force.
https://doi.org/10.17487/RFC9110

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5
