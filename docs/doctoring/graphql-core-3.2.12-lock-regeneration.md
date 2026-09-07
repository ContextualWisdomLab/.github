# graphql-core 3.2.12 Strix lock regeneration

Date: 2026-09-01
Repository: `ContextualWisdomLab/.github`
Pull request: #1570
Protected base: `5686de41660d51a7a7f22b8840dfa6ccfe5ff3f1`

## Root cause

The first #1570 head reused the reviewed `requirements-strix-ci-hashes.txt` blob from stale Dependabot PR #1515. The dependency version and hashes were valid, but copying the blob did not prove that the current protected-main inputs still reproduce the lock through this repository's declared `uv pip compile` contract.

## Exact regeneration

A temporary read-only pull-request workflow checked out exact head `a64a59a6c5aa37d615d17eecbea68bc186f03a24`, downloaded the repository-pinned `uv` archive, verified its SHA-256 digest, verified the exact executable version, and ran the command declared in `CLAUDE.md` and in the generated lock header:

```text
uv 0.12.1 (x86_64-unknown-linux-gnu)
uv pip compile --generate-hashes --python-version 3.13 --python-platform x86_64-manylinux_2_28 --override requirements-strix-ci-overrides.txt --output-file requirements-strix-ci-hashes.txt requirements-strix-ci.txt
```

Tool archive SHA-256:

```text
90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb
```

Combined `requirements-strix-ci.txt` + `requirements-strix-ci-overrides.txt` input SHA-256:

```text
bac58f2e5a276b3f14834aef311f5579e8977809357306f86d2e037d53ee403a
```

Regenerated output SHA-256:

```text
e33fd915f346e4c14fe3f59d1faa848e73fcb38399bf69f86e30f88d7cde9020
```

The regenerated file was byte-identical to the pre-existing #1570 lock. Relative to the protected base, the complete lock delta is exactly:

```diff
-graphql-core==3.2.11 \
-    --hash=sha256:0b3e35ff41e9adba53021ab0cef475eb18f57c7f53f0f2ca55567fbf3c537ea0 \
-    --hash=sha256:e7e156d10beb127cab5c89ff0da71416fc73d27c484a4757d3b2d35633774802
+graphql-core==3.2.12 \
+    --hash=sha256:3d8f104532070485e13caa4092c1e71cda2ba6cffd96e98f285111ee10ed1e51 \
+    --hash=sha256:4579094d5fc8a1a59555a9b18e51b320779d9bbc63e2302c519af0c4919d9543
```

## Hosted evidence

- GitHub Actions run: `33488242489` (`Regenerate Strix lock 1570`)
- Job: `99793293217` (`regenerate`) — terminal `success`
- Artifact: `9792662318`, `strix-lock-regeneration-1570-a64a59a6c5aa37d615d17eecbea68bc186f03a24`
- Artifact digest: `sha256:92b7c3eb4925f85fc18c57719e45d35eca016e889526d99878e2895ee6304280`
- Artifact payload records the command, exact uv version, base/head SHA, input hash, output hash, regenerated lock and base-relative diff.

The temporary workflow has no write permission and is removed from the PR branch immediately after this evidence is captured. Its artifact is evidence only; it is not a runtime or merge bypass.
