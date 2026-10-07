# Noema document-reader runtime on self-hosted workers

The exact-head Noema job for .github#2373, run 36256598579 job 108504745563,
terminated before model review on 2026-09-27 with exit 127: the local HWP reader
version probe could not find `node`. This is a runtime prerequisite failure,
not provider capacity exhaustion or a product review verdict.

The workflow now provisions Node.js 22.23.3 through the exact-pinned setup-node
v4 action before provisioning the gateway sidecar. The reader already accepts
Node 20 or 22 and uses its reviewed local npm lock with lifecycle scripts
disabled. This removes an implicit hosted-image prerequisite without modifying
providers, model deadlines, reader dependencies, review sufficiency, or retry
limits. It also avoids occupying a runner for gateway discovery before learning
that the local document reader cannot start.

The regression asserts the pinned version, action revision and preparation
order. A local workflow contract pass is not proof of hosted review approval;
a fresh exact-head run still must execute the reader and publish a real verdict.
