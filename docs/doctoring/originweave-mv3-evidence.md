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

## 2026-09-19 protected-main adoption and Node 24 artifact action repair

Protected `.github/main@e6334e229581a918e2f22de18733b76fa65d7e71`
was adopted by ordinary two-parent commit
`09f3506b7ecc8f09ed766b3f7e804e05cc8a8139`, preserving the prior owner head
`afeffe3b6a7a5494be1dae12322a0fc2a78c6efe` as ancestry while taking the
current protected tree as the basis for the three MV3 owner paths. No force
update or stale whole-file restoration was used.

The previous workflow pinned
`actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`
(v4.6.2). Hosted consumer evidence had already shown Node-20 deprecation and
`punycode` / `url.parse()` warnings under forced Node 24 execution. The owner
contract therefore gained a RED at
`49fd0e3615ed0cfddca3af9c6d9ff011a6e00194` requiring the exact Node-24-native
`actions/upload-artifact` v7.0.1 commit and rejecting the old v4.6.2 pin. The
minimal GREEN at `5639dc6ab9b9575654dd2626bc06910c03952981`
changes only that action pin in the workflow.

The upstream tag `actions/upload-artifact@v7.0.1` resolves to exact commit
`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`, and its published `action.yml`
declares `runs.using: node24`. The browser version, archive SHA-256 values,
sandbox helper ownership/mode, `CHROME_DEVEL_SANDBOX`, egress boundary,
caller-repository check, evidence paths, retention, and absence of secrets are
unchanged. This repairs the action runtime itself rather than suppressing the
warning or weakening sandboxing.

Fresh exact-head hosted checks and independent review are still required. This
owner repair does not by itself make OriginWeave #299 browser-green; after the
owner lands on protected main, the consumer must pin that immutable protected
revision and replay all required real-browser trials and page-observed
post-conditions.
