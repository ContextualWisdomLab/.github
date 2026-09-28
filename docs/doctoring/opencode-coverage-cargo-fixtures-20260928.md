# OpenCode coverage Cargo fixture intake (2026-09-28)

## Incident

The current-head `.github#1026` OpenCode dispatch run `36348910783`, job
`108722448709`, reached the isolated coverage sandbox. Its full suite reported
four failures in `test_materialize_base_rust_dependencies.py` and
`test_maturin_offline_build_contract.py`, each before the tested behavior at
`cargo generate-lockfile` (3,538 passed, 4 failed, 4 skipped). The PR does not
change either test file. Both files construct registry-backed crates (`itoa`,
`ryu`, and PyO3) during the test, while the sandbox runs with `--network=none`
and its base-repository Rust materializer finds no Cargo lock in this PR's
validated base tree.

With a fresh `CARGO_HOME` and `CARGO_NET_OFFLINE=true`, the two representative
tests failed at the same command. A direct `cargo generate-lockfile` on the
`itoa` fixture reported `no matching package named itoa found` in the offline
crates.io index. This establishes missing registry fixture input, rather than
a product-code assertion failure. The original hosted test helper captures
Cargo stderr, so the hosted log alone does not identify the missing crate.

## Repair and trust boundary

A trusted, lockfile-pinned fixture manifest covers the three registry crates
used by these tests. The networked coverage image build fetches that exact
closure with `cargo fetch --locked`. The PR tree never enters that build
context. The later untrusted test container still has `--network=none` and
receives only the trusted image's cached registry artifacts, copied into its
isolated `CARGO_HOME`. Existing base-repository Rust vendor configuration and
the sandbox's credentials and network restrictions remain in force.

The image build fails if the trusted fixture files are absent, symbolic links,
or cannot be fetched against their checksummed lock. It does not turn a failed
test into a pass.

## Verification boundary

With the fixture cache and offline Cargo, three of the four previously failing
tests passed locally. The PyO3 extension build reached its real offline
compile step, then exceeded that test's 600-second limit on this concurrently
loaded macOS host. That is incomplete local proof for the compile path; a
terminal hosted rerun is required before claiming the coverage gate repaired.
The targeted workflow contract suite passed 82 tests with `GITHUB_ACTIONS=true`.
