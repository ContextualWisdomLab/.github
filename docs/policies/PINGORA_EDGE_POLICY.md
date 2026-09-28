# Cloudflare Pingora Edge Runtime Policy

## Binding rule

ContextualWisdomLab production and test edge runtimes use **Cloudflare Pingora**.
Active Nginx containers, packages, commands, configuration files, Kubernetes
Nginx ingress annotations/classes, and host-service units are prohibited.

This is a runtime boundary, not a vocabulary ban. Documentation, license notices,
dedicated source fixtures under `tests/fixtures/`, the scanner source itself, and
migration histories may name Nginx. Executable integration and end-to-end test
helpers remain runtime candidates. Pull requests that modify a runtime candidate
are evaluated against the final exact head file, so deleting a legacy artifact is
allowed while preserving it or introducing a new one fails closed.

## Why this is not a search-and-replace

Pingora is a programmable Rust framework rather than an Nginx configuration
interpreter. The organization therefore maintains reusable, versioned Pingora
static-serving and proxy artifacts and gives product repositories only declarative
route/site contracts. Product repositories do not fork proxy internals.

## Required migration contract

1. Inventory the current listener, host/path matching, TLS ownership, static root,
   upstream protocol, WebSocket/streaming behavior, body/timeout limits, headers,
   health probes, metrics, and rollback path.
2. Reproduce those behaviors with the approved Pingora artifact and a versioned
   route/site manifest.
3. Add behavior-level tests before deleting the old runtime artifact.
4. Pin Pingora to an exact release at or above `0.8.0`; the shared baseline is
   `0.8.1`. Do not use the experimental Pingora cache integration in the initial
   migration.
5. Preserve certificate data and rollback evidence, but never keep a runnable
   Nginx fallback after cutover. Rollback means redeploying the prior application
   release behind Pingora, not reintroducing Nginx.
6. Treat PHP/FastCGI workloads as application-runtime migrations: place an
   HTTP-capable PHP application server or a reviewed FastCGI adapter behind
   Pingora before cutover. Pingora must remain the public HTTP/TLS edge.

## Ownership

- `.github` owns the binding policy, scanner, shared contracts, and required gate.
- `linux-cluster-ops` owns environment-specific listeners, certificates, routes,
  service units, backups, rollout, and host cutover.
- Each product owns its static build or upstream application behavior and tests.
- Keyverse remains the identity authority; an edge runtime never becomes the
  identity system of record.

## Enforcement and evidence

The organization-required `required-workflow-bootstrap` job runs trusted
base-branch scanner code at the immutable required-workflow SHA. It reads bounded
changed-file metadata and final UTF-8 content through GitHub's REST API. It does
not check out or execute pull-request content and receives only read permissions.
Malformed, truncated, symlinked, oversized, or unavailable runtime evidence fails
closed. Documentation PNG screenshots and PDF papers without a text diff are
excluded only after bounded format verification; PNG evidence must be a complete
CRC-valid chunk stream ending at IEND with conforming chunk names, palette
bounds, and palette indices whose bounded null- or Adam7-interlaced decompressed
scanlines match IHDR.
This is a bounded binary-evidence classifier, not a general image renderer;
visual fidelity and optional ancillary-chunk semantics are outside this gate.
Other binary files remain unavailable evidence and fail closed.

## Declared research/data artifact paths

The scanner's binary exemption is otherwise shaped by path only (`doc`/
`docs`/`documentation`, plus the `evidence`/`figures` publication
directories). A research repository whose raw data and fitted-model
artefacts live elsewhere by deliberate, owner-approved design -- SPSS
`.sav` files, serialized model objects, compressed numeric arrays -- can
opt in without relocating that data under `docs/`.

Add `.github/edge-policy-artifact-paths.txt` at the repository root: one
explicit relative path prefix per non-blank line, no globs or wildcards.
For example:

```
local
evidence/raw
```

**Security property.** `evaluate_pull_request` resolves this file only
from the pull request's *base ref* -- never its head. A pull request that
adds or widens the declaration is not self-authorizing: it gets no benefit
from that change until the change itself is reviewed and merged into the
base branch. This mirrors how the required workflow already treats every
other piece of policy evidence -- current-head content only, no
pull-request-controlled trust.

**What the declaration replaces, and what it does not.** A file under a
declared prefix is admitted on exactly the same evidence documentation
paths already require: `_runtime_path_rule` matches (`Dockerfile`,
`nginx.conf`, service files, and the like) are rejected inside a declared
prefix exactly as inside `docs/` today, and any file that decodes as valid
UTF-8 is still fully content-scanned, never silently admitted. A file whose
suffix has a known magic byte (`.hwpx`, `.pdf`, `.png`) is verified by that
format's structural evidence; a file with no known magic entry (most
research-data formats) is admitted only on the stricter combination of "no
diff patch", "the fetched bytes are not valid UTF-8", and "the
replacement-decoded content contains no prohibited runtime pattern". A text
file cannot be mistaken for a binary artefact merely by sitting under a
declared prefix, and a stray invalid byte cannot hide a readable runtime
directive.

**Bounds.** The declaration is capped at 64 entries and 8 path segments of
depth per entry (`MAX_DECLARED_ARTIFACT_PREFIXES` /
`MAX_DECLARED_ARTIFACT_PREFIX_DEPTH` in `scripts/ci/pingora_edge_policy.py`)
-- parsing-safety bounds, not a product limit on how many locations a
repository may declare. An absolute path, a `..` traversal component, a
bare `.`/`/`, or a glob character in any entry is a hard `PolicyError`
naming the offending entry; a repository with no declaration file behaves
identically to before this feature existed. When a declared prefix admits a
file, the required workflow logs a `::notice::` naming the prefix and the
base ref the declaration was read from, so a reviewer can trace the
admission back to the reviewed declaration it relied on.

Refs #2193, #2149, #2116.

## Exception process

There is no standing Nginx exception. A temporary exception requires a public ADR
with an owner, exact affected asset, buyer impact, security controls, removal date,
and an approved Pingora migration PR. The central scanner remains unchanged; the
exception is implemented by completing the migration before merge.
