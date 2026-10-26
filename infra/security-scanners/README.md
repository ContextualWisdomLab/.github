# Socketless scanner source (activation held)

Trusted image-owner tooling, **not code to execute from a PR checkout**. This additive source package does not migrate any job, install an image, or replace the security workflow. PR #2664's independent Gitleaks/Python isolation repair remains intact and separately owned.

## Offline acquisition and installation contract

`acquire_tools.py` is an offline verifier, not a downloader. On a trusted image-build host, provide owner-controlled retained public artifacts in `EVIDENCE`, then run:

```sh
python3 -I -B acquire_tools.py --evidence "$EVIDENCE" --output "$NEW_TOOLS"
```

The output directory must not exist. Input filenames are the two
`osv-scanner-action` / `scorecard-action` `.manifest.raw.json` and
`.config.raw.json` pairs, five `<compressed-layer-sha256>.tar.gz` files selected
by their manifest descriptors, `gitleaks_8.30.1_linux_x64.tar.gz`,
`gitleaks_8.30.1_checksums.txt`, and `gitleaks-v8.30.1-release.json`.
The exact manifest, member and release pins are executable policy in
`acquire_tools.py`; `tools/inventory.json` is the independently verified expected
five-member inventory. Compare recovered inventory with it before installation.

The helper checks raw manifest pins, config/layer digest and size, Linux/amd64,
bounded decompression, OCI diff IDs and unique exact regular members. It does
not extract arbitrary paths. Outputs include six members (the upstream wrapper
is test evidence), inventory and membership receipts. This proves digest-bound
supplier artifact membership, not publisher signatures, reproducible builds or
complete image-overlay admission. Do not substitute mutable tags or arbitrary
release archives when a pin is unavailable.

A separately reviewed image installer must install the verified scanner,
reporter, Scorecard and Gitleaks executables plus inventory and `adapter.py` into
root-owned, workload-unwritable `/opt/security`; install the verified policy at
**both** `/opt/security/policy.yml` and `/policy.yml`. Use executable mode 0555
for binaries, readable mode 0444 for policy/inventory/source, and non-root UID
1001:1001. Verify both policy copies against the inventory after image creation:
the adapter checks the `/opt/security` copy, not the root copy. Reject writable
parents, links or mounts replacing those trusted paths. The source helper does
not defend a concurrently hostile owner filesystem.

Invoke only installed immutable source:
`python3 -I -B /opt/security/adapter.py osv-head` (or another enumerated stage).
The working directory must contain the intended `source/` checkout for OSV,
with owner-created writable `/work/home`, `/tmp`, and artifact output directory.
The caller must impose a finite deadline and terminate the entire owned process
group/container; the adapter deliberately adds no independent timeout. Scan-only
exit 128 maps to 0; other scanner/report exits and shell signal statuses remain.
Scorecard stdout/stderr are suppressed because upstream validation can print a
token. Artifact privacy and token-bearing API behavior need separate acceptance.
Trivy is an unprovisioned optional command: this inventory omits it and execution
fails closed. Gitleaks is acquired for the existing separate invocation; the
adapter does not expose a Gitleaks stage.

## Portable focused tests

From this directory (Python 3.10+ and Bash):

```sh
python3 -B -m unittest -v test_adapter
python3 -I -B provenance_regressions.py .
# OUT is a fresh owner-created writable evidence directory:
python3 -I -B parity_regressions.py . exit_code_redirect.sh "$OUT"
```

The 9 adapter, 12 archive-admission and 2 parity tests use synthetic executables
and archives, not native scanner findings. `exit_code_redirect.sh` is unchanged
Apache-2.0 upstream test evidence, SHA-256
`4b6d24e5727c636a8a897545f2496223c9ed4426e2692dd096b0b4d08fd1725c`.

## Native evidence and explicit remaining gates

Retained independent source review SHA-256:
`71b4b7de3975ab716379665eac83f559e10958de9001e52c05727415e3350287`.
Reviewed adapter SHA-256:
`01e7391f1958c5ed1d1ee30e4dcc5b5e161495a4be0a003be6165d28e81f6888`;
acquisition SHA-256:
`a8381051392ebbd2aa0621a94d9ae60f4288c1df947202801e9d6e90444c15fd`.
The separate bounded S1 native fixture ran exact OSV/reporter bytes: npm lodash
4.18.1 clean exits 0; 4.17.20 exits 1 with five findings; differential reporter
produced five SARIF results (exit 1), clean→clean zero (exit 0). No npm install or
package script ran. Scorecard without a token refused (exit 1); that is not
successful token-bearing coverage. Native receipts remain owner-retained, not
embedded synthetic results in this repository.

**All six workflow invocation substitutions remain unapplied and held.** The
public-workflow route is not admitted. Next action is a separately reviewed
immutable Linux/amd64 image installer/build with the verified acquisition
outputs, both policy paths, Python and Go/toolchain parity (including the
required Go 1.26.5 behavior). Do not use the old partial Docker recipe as a
ready-to-run workload image. Then obtain bounded target-dependency/ecosystem,
token-bearing Scorecard/API/artifact privacy, Actions SARIF upload and
harden-runner socketless acceptance, immutable image custody and shared public
runner admission before proposing workflow activation. No host Docker socket,
new VM, registration, dispatch, protection change or merge is authorized here.
