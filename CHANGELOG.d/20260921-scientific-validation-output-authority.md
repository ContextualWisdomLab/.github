### Fixed

- Scientific-validation verifier receipt publication now reuses one pinned directory authority when predicate and manifest outputs share a normalized parent, preventing a real-directory pathname replacement between independent parent acquisitions from splitting one logical receipt pair across directory generations (#2318).
- Output-parent exclusion now compares the acquired directory descriptor identity against the already-pinned sealed-root directory identity, so renaming the sealed evidence directory onto a different output pathname cannot make the verifier publish receipts back into the sealed evidence inode (#2319).
- Distinct-parent output remains supported with independently pinned descriptors; no-clobber publication and unsigned local-integrity boundaries are unchanged.
