# Scientific-validation output authority

Issues #2318, #2319, and #2320 close receipt-publication authority and durability gaps left after #2305. The verifier pins output parents by descriptor and publishes predicate/manifest leaves without clobbering existing files, but a complete signer handoff also needs one logical receipt pair to stay on the intended directory authority and for a successful return to represent crash-durable final directory entries.

## Shared-output parent generation finding (#2318)

Before #2318, `verify()` called `_validate_output_path()` independently for the predicate and manifest. A local actor able to rename the output directory could let the predicate acquisition pin directory generation A, rename A away, create a fresh real directory generation B at the same pathname, and let the manifest acquisition pin B. No symlink was required, so the component-wise `O_DIRECTORY | O_NOFOLLOW` walk remained satisfied. The verifier could then publish one logical receipt pair across two directory generations.

The source-level hostile contract is commit `f42d810e37c94c80306da14aaf2c66f5b30bfda0`. It replaces the shared parent with a fresh real directory after the first authority acquisition and requires both receipt leaves to remain in the originally pinned directory. The predecessor performs a second acquisition and splits the pair.

Causal production repair `7ac61d0daacf91e75df63ccc8073ece3ea43be40` normalizes both output paths before either parent acquisition. Identical leaf paths are rejected first. When the normalized parent is shared, `_validate_output_path()` is called once and that one descriptor is reused for both predicate and manifest leaf preflight and publication. Distinct-parent output remains supported and receives independent pinned descriptors.

Test alignment and branch coverage are commit `e87b1c5713075f7837de5c72dabdfb3dd8873187`: the prior post-acquisition pathname-swap contract now swaps after the single shared-parent acquisition, the #2318 real-directory replacement RED is retained, and a successful distinct-parent case covers the non-shared authority path.

## Sealed-root rename alias finding (#2319)

After #2318, output containment was still decided from the sealed root's original absolute pathname. The evidence root itself is pinned by descriptor, so a local namespace writer can rename that already-open directory to a different pathname before output-parent validation. If the caller supplied that new pathname as the output parent, the old pathname containment check passes even though the acquired output-parent descriptor and sealed-root descriptor identify the same `(st_dev, st_ino)` directory authority.

Source-level hostile RED `24dc91401a3d4e0ddf277a79a036c2f9336b8808` renames the pinned one-member sealed root onto the preselected output-parent pathname before `_validate_output_path()` opens it. The predecessor admits the alias, passes cardinality while the root still contains only the evidence member, then publishes predicate and manifest into the sealed directory after evidence intake.

Causal repair `e6c10a25f348eee0cdc5a5e6eba211b35b571c7a` adds descriptor-identity exclusion. Every acquired output-parent descriptor is compared with the already-pinned sealed-root descriptor; matching `(st_dev, st_ino)` identities fail closed with the existing `verifier outputs must remain outside the sealed evidence root` contract. The pathname containment check remains as an early diagnostic, while inode authority is the final same-directory decision. Because the sealed root must contain exactly one evidence member before publication, an output subdirectory inside it would already violate cardinality; the repair therefore targets the remaining same-directory rename alias without widening path policy.

## Crash-durable final receipt names (#2320)

The #2306 no-clobber writer fsyncs the temporary receipt inode before linking it to the final leaf, but the predecessor did not fsync the containing directory after `link(2)`. Linux `fsync(2)` states that file synchronization does not necessarily make the containing directory entry durable and that an explicit `fsync()` on a directory descriptor is required. That distinction matters here because the manifest is the receipt completion marker: returning success before its final directory entry is synchronized can leave a successful verifier invocation whose completion marker disappears after a crash or reboot.

Source-level RED `047d1d90b6db82231c91625c9dd81f28e1debba0` adds two contracts under the existing 100% owned branch-coverage lane. One records every `fsync()` target and requires a successful receipt publication to synchronize both a regular-file descriptor and a directory descriptor. The other injects a directory-descriptor `fsync()` failure and requires a typed `EvidenceError` instead of a successful publication result.

Causal production repair `0982584de36114b5bf38149276ecbf4e6680f42e` keeps the already-pinned output-parent descriptor open through hard-link publication and explicitly `fsync()`s that descriptor after the final leaf is linked. A parent-directory synchronization `OSError` is normalized to `EvidenceError("output directory synchronization failed")`. The already-linked leaf is deliberately not removed on synchronization failure: rollback by pathname would reintroduce the check-then-unlink race rejected in #2307. Callers must treat the verifier's nonzero result as incomplete even if an unsynchronized leaf is visible in the current namespace.

This follows POSIX/Linux file durability semantics rather than introducing a new scientific claim. The file payload is synchronized first, the final name is created with no-clobber descriptor-relative hard-link semantics, and the containing directory is synchronized before the writer reports success. Shared-parent and distinct-parent publication both use the same primitive, so each successful final leaf receives the same durability boundary.

CHANGELOG currentization for #2315–#2320 is `7361f8e98418202b2b67b6f8501b0f1164b59924`. The focused tests remain in `tests/test_scientific_validation_evidence_output_safety.py`, which is already part of the Scientific Validation Evidence Quality 100% owned branch-coverage lane and compileall path.

## Preserved contracts

The fixes preserve no-clobber hard-link publication, exact predicate-byte hashing, manifest completion-marker semantics, one-member sealed evidence, descriptor-relative operations, shared/distinct output-parent support, and typed fail-closed errors. They do not add signer credentials or OIDC authority.

## Boundary

This is local filesystem integrity and crash durability for an unsigned verifier receipt. It does not authenticate the GitHub run, workflow source, artifact producer, caller, signer, Sigstore bundle, or psychometric acceptance. #2164 remains the reusable-workflow OIDC source-identity prerequisite. #2299 remains responsible for live GitHub metadata re-resolution, credentialed signing, immutable reviewed attestation, cross-repository canary verification, and online/offline bundle verification. TEPP #637 must continue to consume only released or immutable-pinned authenticated owner authority.
