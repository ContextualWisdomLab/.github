# Release sidecar runtime adoption

The immutable release helper at 4b0c6b75 predates the shared-runtime fix from #2468. Updating central main or rerunning an old immutable workflow cannot make that checkout consume the fix.

All three release helper checkouts and their identity guards now pin protected-main ancestor e45f1b144aef900d734ff4c900f9e0010fd5a32d. The scripts/ci tree is 7f902df89a925f89c4fae69a842508406cd0207c; the requirements blob remains eb83beda177c9d2e4ca9b7e2888a1ccb55a123ac. The entire scripts delta from the prior helper is the six-line shared Python-library binding. Origin, commit, tree, clean-file and sibling checks remain intact.

Independent guest-02 probes confirmed the selected 3.12.14 executable loaded the 3.12.3 runtime under inherited paths; the exact patched prefix selects 3.12.14 and passes logging/asyncio imports. The shared sidecar contracts passed 31 tests locally and in CI mode before #2468 merged; its whole merged tree matched the tested tree. This adoption does not claim hosted Noema acceptance, source grant clearance, release publication or a twelve-wheel verdict. The fast caller must separately adopt this callee revision.
