# Scientific-validation output authority

Issues #2318 and #2319 close receipt-publication authority gaps left after #2305. The verifier already pins each output parent by descriptor and publishes predicate/manifest leaves without clobbering existing files. That was not sufficient when two logical pathnames could resolve to different directory generations or when a renamed sealed-evidence directory could later be reused as an output parent under a different pathname.

## Shared-output parent generation finding (#2318)

Before #2318, `verify()` called `_validate_output_path()` independently for the predicate and manifest. A local actor able to rename the output directory could let the predicate acquisition pin directory generation A, rename A away, create a fresh real directory generation B at the same pathname, and let the manifest acquisition pin B. No symlink was required, so the component-wise `O_DIRECTORY | O_NOFOLLOW` walk remained satisfied. The verifier could then publish one logical receipt pair across two directory generations.

The source-level hostile contract is commit `f42d810e37c94c80306da14aaf2c66f5b30bfda0`. It replaces the shared parent with a fresh real directory after the first authority acquisition and requires both receipt leaves to remain in the originally pinned directory. The predecessor performs a second acquisition and splits the pair.

Causal production repair `7ac61d0daacf91e75df63ccc8073ece3ea43be40` normalizes both output paths before either parent acquisition. Identical leaf paths are rejected first. When the normalized parent is shared, `_validate_output_path()` is called once and that one descriptor is reused for both predicate and manifest leaf preflight and publication. Distinct-parent output remains supported and receives independent pinned descriptors.

Test alignment and branch coverage are commit `e87b1c5713075f7837de5c72dabdfb3dd8873187`: the prior post-acquisition pathname-swap contract now swaps after the single shared-parent acquisition, the #2318 real-directory replacement RED is retained, and a successful distinct-parent case covers the non-shared authority path.

## Sealed-root rename alias finding (#2319)

After #2318, output containment was still decided from the sealed root's original absolute pathname. The evidence root itself is pinned by descriptor, so a local namespace writer can rename that already-open directory to a different pathname before output-parent validation. If the caller supplied that new pathname as the output parent, the old pathname containment check passes even though the acquired output-parent descriptor and sealed-root descriptor identify the same `(st_dev, st_ino)` directory authority.

Source-level hostile RED `24dc91401a3d4e0ddf277a79a036c2f9336b8808` renames the pinned one-member sealed root onto the preselected output-parent pathname before `_validate_output_path()` opens it. The predecessor admits the alias, passes cardinality while the root still contains only the evidence member, then publishes predicate and manifest into the sealed directory after evidence intake.

Causal repair `e6c10a25f348eee0cdc5a5e6eba211b35b571c7a` adds descriptor-identity exclusion. Every acquired output-parent descriptor is compared with the already-pinned sealed-root descriptor; matching `(st_dev, st_ino)` identities fail closed with the existing `verifier outputs must remain outside the sealed evidence root` contract. The pathname containment check remains as an early diagnostic, while inode authority is the final same-directory decision. Because the sealed root must contain exactly one evidence member before publication, an output subdirectory inside it would already violate cardinality; the repair therefore targets the remaining same-directory rename alias without widening path policy.

CHANGELOG currentization is `7af3ec67ef949d4953b3b3ef073faf210c3006aa`. The focused hostile test remains in `tests/test_scientific_validation_evidence_output_safety.py`, which is already part of the Scientific Validation Evidence Quality 100% owned branch-coverage lane.

## Preserved contracts

The fixes preserve no-clobber hard-link publication, exact predicate-byte hashing, manifest completion-marker semantics, one-member sealed evidence, descriptor-relative operations, shared/distinct output-parent support, and typed fail-closed errors. They do not add signer credentials or OIDC authority.

## Boundary

This is local filesystem integrity for an unsigned verifier receipt. It does not authenticate the GitHub run, workflow source, artifact producer, caller, signer, Sigstore bundle, or psychometric acceptance. #2164 remains the reusable-workflow OIDC source-identity prerequisite. #2299 remains responsible for live GitHub metadata re-resolution, credentialed signing, immutable reviewed attestation, cross-repository canary verification, and online/offline bundle verification. TEPP #637 must continue to consume only released or immutable-pinned authenticated owner authority.
