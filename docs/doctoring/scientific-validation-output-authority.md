# Scientific-validation output authority

Issue #2318 closes a receipt-publication authority gap left after #2305. The verifier already pins each output parent by descriptor and publishes predicate/manifest leaves without clobbering existing files. That was not sufficient when both output paths named the same parent pathname.

## Finding

Before #2318, `verify()` called `_validate_output_path()` independently for the predicate and manifest. A local actor able to rename the output directory could let the predicate acquisition pin directory generation A, rename A away, create a fresh real directory generation B at the same pathname, and let the manifest acquisition pin B. No symlink was required, so the component-wise `O_DIRECTORY | O_NOFOLLOW` walk remained satisfied. The verifier could then publish one logical receipt pair across two directory generations.

The source-level hostile contract is commit `f42d810e37c94c80306da14aaf2c66f5b30bfda0`. It replaces the shared parent with a fresh real directory after the first authority acquisition and requires both receipt leaves to remain in the originally pinned directory. The predecessor performs a second acquisition and splits the pair.

## Decision

Causal production repair `7ac61d0daacf91e75df63ccc8073ece3ea43be40` normalizes both output paths before either parent acquisition. Identical leaf paths are rejected first. When the normalized parent is shared, `_validate_output_path()` is called once and that one descriptor is reused for both predicate and manifest leaf preflight and publication. Distinct-parent output remains supported and receives independent pinned descriptors.

Test alignment and branch coverage are commit `e87b1c5713075f7837de5c72dabdfb3dd8873187`: the prior post-acquisition pathname-swap contract now swaps after the single shared-parent acquisition, the #2318 real-directory replacement RED is retained, and a successful distinct-parent case covers the non-shared authority path.

The fix preserves no-clobber hard-link publication, exact predicate-byte hashing, manifest completion-marker semantics, sealed-evidence exclusion, descriptor-relative operations, and typed fail-closed errors. It does not add signer credentials or OIDC authority.

## Boundary

This is local filesystem integrity for an unsigned verifier receipt. It does not authenticate the GitHub run, workflow source, artifact producer, caller, signer, Sigstore bundle, or psychometric acceptance. #2164 remains the reusable-workflow OIDC source-identity prerequisite. #2299 remains responsible for live GitHub metadata re-resolution, credentialed signing, immutable reviewed attestation, cross-repository canary verification, and online/offline bundle verification. TEPP #637 must continue to consume only released or immutable-pinned authenticated owner authority.
