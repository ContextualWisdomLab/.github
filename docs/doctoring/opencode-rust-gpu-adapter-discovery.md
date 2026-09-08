# Deterministic Rust GPGPU software-adapter discovery

Decision date: **2026-09-08**

## Problem

The OpenCode Rust coverage worker enables Mesa lavapipe on GPU-less hosted
runners. Its adapter selection previously parsed `ls` output through
`head -n1`. GitHub documents that its Bash runner enables `pipefail`, so a
selection pipeline contributes its own process and exit-status behavior to a
coverage prerequisite. Parsing command output is also unnecessary because the
candidate namespace is a trusted local directory and Bash already exposes
matching pathnames as separate values.

## Decision

Inside `ensure_rust_gpu_adapter`, set the function-local collation locale to
`C`, iterate `/usr/share/vulkan/icd.d/lvp_icd*.json`, and select the first
regular file. If the pattern has no regular-file match, preserve the current
no-adapter path. Do not change Rust ownership, wgpu coverage expectations, the
software-rendering environment, or the fail-closed coverage result.

## Verification and failure scenes

The permanent contract rejects the old `ls | head` pipeline and requires the
locale pin, pathname loop, regular-file check, and first-match assignment.
A runner with one or more lavapipe manifests selects one deterministic regular
file. A runner without a matching regular file reports the existing fallback
receipt and continues to expose uncovered GPU code through the ordinary Rust
coverage gate.

## References

Free Software Foundation. (2025). *Bash reference manual: Filename expansion*.
https://www.gnu.org/software/bash/manual/html_node/Filename-Expansion.html

GitHub. (2026). *Workflow syntax for GitHub Actions*. Retrieved September 8,
2026, from https://docs.github.com/actions/using-workflows/workflow-syntax-for-github-actions
