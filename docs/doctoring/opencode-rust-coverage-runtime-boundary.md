# OpenCode Rust coverage runtime boundary

## Decision

The central OpenCode review path treats Rust coverage tooling as part of the trusted evidence boundary. A coverage image is not accepted merely because `cargo-llvm-cov` is present: the image must also contain reviewed, versioned LLVM coverage executables, propagate their exact paths into the isolated runtime, and revalidate those executables before the first coverage invocation.

The reviewed tool paths are `/usr/bin/llvm-cov-19` and `/usr/bin/llvm-profdata-19`. They are intentionally explicit rather than discovered from `PATH`. The trusted image must install Debian `llvm-19`, bind those paths through `LLVM_COV` and `LLVM_PROFDATA`, verify both are executable before installing the pinned cargo-llvm-cov archive, pass the same literal constants through the networkless Docker boundary, and verify both executables again inside the isolated runtime.

This is fail-closed evidence plumbing. A missing, non-executable, changed, or unpropagated tool path invalidates Rust coverage evidence; it must not silently fall back to an ambient host binary, a network installer, an older head, or a generated merge-tree result.

## Root cause and product impact

DiskSage exact-head OpenCode review exposed a central infrastructure defect rather than a DiskSage product defect. The trusted coverage image could contain a pinned `cargo-llvm-cov` binary while the isolated runtime lacked an explicitly compatible `llvm-cov` / `llvm-profdata` pair. That makes successful local or predecessor-head coverage irrelevant to the current review run: the durable central reviewer must independently reproduce coverage in its own restricted execution boundary.

`cargo-llvm-cov` documents `LLVM_COV` and `LLVM_PROFDATA` as explicit overrides and states that the selected `llvm-cov` must be compatible with the LLVM version used by `rustc`. LLVM documents that `llvm-cov` consumes instrumentation-based coverage data and that raw profile data is converted for reporting through `llvm-profdata merge`. The two executables therefore form one compatibility-sensitive evidence chain rather than interchangeable utilities.

## Security boundary

The repair preserves the existing separation between untrusted pull-request source and trusted reviewer execution:

- the coverage runtime remains `--network=none`;
- repository or model credentials are not introduced into the coverage container;
- no Docker socket is exposed to pull-request code;
- the reviewed LLVM paths are immutable workflow-source constants, not contributor-controlled inputs;
- build-time validation catches a malformed trusted image before it can become review infrastructure;
- runtime validation catches propagation or execution-boundary drift before coverage is accepted;
- no `rustup component add`, package installation, or network fallback is permitted during the isolated pull-request measurement step;
- exact-head binding and stale-head refusal remain independent requirements; and
- coverage success remains evidence, not durable merge or release authorization.

The change does not alter the existing review-agent model credential contract or authorize `COPILOT_GITHUB_TOKEN`. It changes only the deterministic Rust coverage toolchain carried into the isolated evidence runtime.

## Verification contract

`tests/test_opencode_rust_coverage_toolchain_contract.py` is the permanent source-level regression contract. It requires, in order:

1. Debian `llvm-19` in the trusted image;
2. exact `LLVM_COV=/usr/bin/llvm-cov-19` and `LLVM_PROFDATA=/usr/bin/llvm-profdata-19` image bindings;
3. executable checks for both paths before the pinned cargo-llvm-cov archive;
4. literal propagation of both reviewed constants through `docker run` before the coverage image argument; and
5. a second executable check after the Docker boundary and before the first `cargo llvm-cov` invocation.

The contract deliberately checks ordering as well as presence so a dead comment, post-coverage assertion, or unrelated environment declaration cannot satisfy the gate.

## Rollback and migration

Rollback is a reviewed workflow change, not a runtime bypass. If the Rust toolchain later moves to a different LLVM major version, update the Debian package, both versioned paths, the build-time and runtime assertions, this doctoring record, and the regression contract together. First prove the new compatibility requirement with a failing test, then rerun the complete exact-current-head central CI, security, coverage, docstring, packaging, provenance, and review suite. Do not revert to unversioned `PATH` discovery merely to make a failing review green.

Repositories consuming the central reviewer require no migration. Standalone repository operation is unchanged; the change only makes central review evidence deterministic. Modular CWL services such as DiskSage, Naruon, contextual-orchestrator, and other consumers continue to call the same central review contract and receive no additional runtime authority.

## Standards and primary-source evidence

NIST SP 800-218 SSDF Version 1.1 remains the current final publication and recommends integrating secure development practices into the SDLC. NIST published SP 800-218 Rev. 1 / SSDF Version 1.2 as an Initial Public Draft on December 17, 2025; it is recorded here as draft evidence, not as a final standard. The implementation choice here is narrower than either publication: it makes one build/test toolchain reproducible and fail-closed and does not claim SSDF conformance or certification.

LLVM's current command documentation identifies `llvm-cov` as the coverage reporting tool and `llvm-profdata` as the profile-data utility used to merge instrumentation profiles. The cargo-llvm-cov project documents the `LLVM_COV` and `LLVM_PROFDATA` override variables and explicitly requires LLVM compatibility with the LLVM version used by `rustc`. These primary technical sources support binding and validating a reviewed compatible pair rather than relying on ambient discovery.

## APA 7th references

LLVM Project. (2026). *llvm-cov—Emit coverage information*. https://llvm.org/docs/CommandGuide/llvm-cov.html

LLVM Project. (2026). *llvm-profdata—Profile data tool*. https://llvm.org/docs/CommandGuide/llvm-profdata.html

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development Framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Booth, H., Ogata, M., Kent, K., Souppaya, M., & Dodson, D. (2025). *Secure Software Development Framework (SSDF) version 1.2: Recommendations for mitigating the risk of software vulnerabilities* (Initial Public Draft, NIST Special Publication 800-218 Rev. 1). National Institute of Standards and Technology. https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

Taiki Endo. (2026). *cargo-llvm-cov: Cargo subcommand to easily use LLVM source-based code coverage*. GitHub. https://github.com/taiki-e/cargo-llvm-cov

## Reference verification note

The LLVM command guides, cargo-llvm-cov primary repository documentation, NIST SP 800-218 Version 1.1 final publication, and the SP 800-218 Rev. 1 Version 1.2 Initial Public Draft were rechecked on August 7, 2026. The draft status of Version 1.2 is intentionally preserved so it is not misrepresented as a final international or U.S. government standard.
