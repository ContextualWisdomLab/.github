# Sandboxed verification symlink boundary

## Incident

The review verifier copied an untrusted checkout with `shutil.copytree(...,
symlinks=True)`. That preserves symbolic links rather than copying their
targets. A pull request could therefore add an absolute link, or a relative
link containing enough parent traversal, that a verification command followed
outside the temporary repository. Environment scrubbing did not close that
filesystem boundary.

## Decision

After applying the copy ignore policy, and before running the untrusted command,
the verifier walks the exact copied tree without following directory links and
validates every symbolic link. An absolute target is rejected because the copied
link would still point at a host path. A relative target is accepted only when
its fully resolved path remains beneath the copied repository. Safe internal
relative links remain links so project semantics are preserved. Links under
ignored paths such as `node_modules` never enter the copy and are not evaluated.

The validation happens before the untrusted command starts. Rejection is
fail-closed with stable exit code `122`, `path_boundary_rejected=true` in the
machine-readable result, and a generic diagnostic that does not disclose the
resolved host target. It produces no verification success evidence. This is
filesystem containment, not an operating-system sandbox claim; the existing
network-mode field remains evidence metadata rather than enforcement.

The walk is intentionally a pre-execution copy validation, not a continuous
kernel-enforced filesystem sandbox. A command may create a new symlink after
validation. The wrapper therefore does not claim to contain a hostile process
that can mutate its copied workspace during execution; that stronger boundary
belongs to the surrounding runner or container. The control closes exposure
introduced by attacker-supplied links already present in the copied checkout.

## Test-first evidence

`tests/test_sandboxed_verify_symlink_boundary.py` first reproduced the defect:
an escaping repository link copied successfully instead of raising. The
accepted tests require rejection of both relative traversal and absolute links,
including an absolute link back into the original checkout, while retaining a
safe repository-internal relative link.

## Failure, recovery, and rollback

Repositories that intentionally contain absolute or escaping links must replace
them with bounded relative links before review verification. A rollback is safe
only if an independently reviewed replacement proves that no path available to
the copied command can resolve outside the copy. Dereferencing untrusted links
during the copy is not an acceptable fallback because it can read the external
target while constructing the sandbox.

## APA 7th reference

Python Software Foundation. (2026). *shutil—High-level file operations*
(Python 3.14 documentation). Retrieved August 11, 2026, from
https://docs.python.org/3.14/library/shutil.html#shutil.copytree
