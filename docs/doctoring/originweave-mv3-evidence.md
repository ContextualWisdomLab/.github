# OriginWeave sandboxed browser evidence

The reusable `originweave-mv3-evidence.yml` workflow owns the trusted runner,
Chrome for Testing supply-chain, sandbox-helper, and artifact mechanics for
OriginWeave's real-browser evidence. Product fixtures and interpretation remain
in OriginWeave; the central workflow executes its checked-out
`scripts/ci/run_mv3_compatibility.py` entry point at the exact caller revision.

The workflow accepts only the OriginWeave repository, grants read-only contents
permission, downloads Chrome and ChromeDriver 150.0.7871.129 over declared
egress, verifies both archives against SHA-256 values recovered from successful
OriginWeave run 33866932365, and configures the archive's root-owned mode-4755
`chrome_sandbox` through `CHROME_DEVEL_SANDBOX`. It receives no secrets and
does not contain product browser policy.

An OriginWeave caller must pin this workflow file to the reviewed protected-main
commit that introduces it. A branch or tag reference is not accepted evidence.
Changing the browser build, checksums, sandbox mechanism, permissions, egress,
or artifact contract requires a new central review and fresh consumer execution.

This owner workflow does not itself prove an OriginWeave feature. Acceptance
still requires an exact-head consumer run whose product-owned runner emits all
required trials and surfaces successfully. Runner unavailability, archive
verification failure, browser-session startup failure, product-contract
failure, and cancellation remain distinct from a successful run.

## 2026-09-09 owner restack verification

The owner branch was behind `main` at `6e356c3ad75bfd978e3dd9d3e20e5596c4df3aa6`.
It was non-force-restacked with `origin/main` as
`9c1417b6366d209a140b74bbd47cddf9597108c9`. The focused workflow contract
passed (`1 passed`), followed by the central suite (`2994 passed, 1 skipped,
21 subtests passed`). The local verifier generated an untracked `uv.lock`; it
is not part of the owner change. This is owner-source evidence only: it does
not establish a reviewed release, a protected-main pin, or a successful
OriginWeave consumer run.
