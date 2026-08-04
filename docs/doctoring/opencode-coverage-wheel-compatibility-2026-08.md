# OpenCode coverage binary-wheel compatibility control

## Decision

The central trusted coverage image may defer one base-commit Python lock only
when pip emits both of the following diagnostics for the same exact requirement:

- `Could not find a version that satisfies the requirement ...`
- `No matching distribution found for ...`

This narrow rule treats the result as an interpreter, ABI, or platform wheel
compatibility mismatch. It does not treat a single resolver line as sufficient
evidence. Hash mismatches, network retries, package-index fetch failures, empty
output, and unknown resolver failures remain fatal.

## Incident evidence

OpenCode coverage run `30900205865`, job `91963234714`, failed while building the
trusted Python 3.14 coverage image. The target repository's trusted base lock
pinned `atheris==3.0.0`; pip reported that only 3.1.0 was selectable and then
reported no matching distribution for 3.0.0. The failure occurred before any
pull-request source was executed, so it was a central sandbox compatibility
outage rather than evidence against the reviewed pull request.

## Security argument

The workflow invokes pip with `--require-hashes` and `--only-binary=:all:`.
Python package wheels declare interpreter, ABI, and platform compatibility tags,
and pip documents that packages without an eligible binary distribution fail
under `--only-binary=:all:` (Python Packaging Authority, 2026a, 2026b). A
trusted pin can therefore be valid for its repository while lacking a wheel for
the centrally selected interpreter.

The control remains fail closed because both pip diagnostics must identify the
same exact requirement and known integrity/network signals take precedence. The
candidate is not silently accepted: the source path and bounded resolver output
remain in the job log. The later networkless coverage phase still fails if the
skipped package is required by the repository's executable test path.

This follows NIST SSDF practices PW.4.1 and RV.1 by maintaining third-party
components securely, continuously analyzing failures, and correcting the shared
software-development infrastructure without weakening integrity controls
(Souppaya et al., 2022).

## Verification

The executable regression suite covers the observed Atheris diagnostic,
one-sided and mismatched diagnostics, network and hash precedence, warning
visibility, and the final skipped-lock count. Existing tests continue to cover
malformed manifests, incomplete hash closures, explicit Python incompatibility,
registry failures, and installation races.

## References

Python Packaging Authority. (2026a). *pip download*. pip documentation.
https://pip.pypa.io/en/stable/cli/pip_download/

Python Packaging Authority. (2026b). *Platform compatibility tags*. Python
Packaging User Guide.
https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of software
vulnerabilities* (NIST Special Publication 800-218). National Institute of
Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
