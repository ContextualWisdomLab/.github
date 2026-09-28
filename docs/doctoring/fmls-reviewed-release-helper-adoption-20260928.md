# Reviewed release helper adoption

The release callee continued checking out helper `5a29e0a5` after central #2457 and #2465 were merged. Advancing the fast caller workflow alone would therefore not execute the reviewed artifact recognition or complete libfuzzer source-obligation checks.

All three callee jobs now pin protected-main ancestor `4b0c6b754fc30a0d0bf77f9c41650e1451476c26`. Their identity guards require scripts tree `f1b96f0a0af5cc30f8c8f2bb662727d41129f7dd`; requirements blob remains `eb83beda177c9d2e4ca9b7e2888a1ccb55a123ac`. Foreign origin, dirty/missing files, incorrect commit/tree and caller-controlled sources remain rejected.

Reviewed #2465 source d0abbd63 integrated on a2ba7972: full merge tree `5b92f72696aae71cfe35ce5d765bf280f4f7d504` exactly equals merged 4b0c6b75. Independently fetched 59 immutable source/grant bodies with exact hash/size agreement; full LLVM modern/legacy terms and CREDITS were read. The 957 affected license tests pass locally and under GITHUB_ACTIONS=true. Adoption workflow/identity suites pass 58 tests in each mode; actionlint (ShellCheck disabled) and diff checks pass.

The scripts-tree delta also includes separate Noema/materializer changes; these are not release-gate entry points. The release sidecar delta enables fatal stack-location diagnostics without frame locals. Strix requirements are unchanged. This is fixed-helper adoption only: fast caller adoption, native execution, original HOLD clearance, and published 12-wheel acceptance remain distinct requirements.
