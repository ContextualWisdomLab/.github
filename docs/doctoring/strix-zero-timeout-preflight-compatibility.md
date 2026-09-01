# Strix zero-timeout preflight compatibility

## Incident

LineageWeave Actions run `33485408780`, job `99784205986`, successfully started the vendored Contextual-Orchestrator sidecar. Health, route discovery, and an independent OpenAI-compatible `/chat/completions` probe all passed. Strix 1.5.3 then printed `LLM CONNECTION FAILED` three times without sending a model request to the gateway.

## Root cause

The central workflow intentionally exports `LLM_TIMEOUT=0` so long-running security inference has no fixed request deadline. Strix already interprets non-positive request timeouts as disabled when building `ModelSettings`, but its main-model and dedupe-model warm-up paths pass the same zero directly to `asyncio.wait_for`. Python treats `timeout=0` as an immediate deadline, cancels the warm-up coroutine, and renders an empty `Error:` because `TimeoutError` has an empty string representation.

The sidecar remained alive until runner orphan cleanup. The failure was therefore inside Strix's preflight boundary, not gateway startup, authentication, routing, or container loopback.

## Repair

Keep `LLM_TIMEOUT=0`. After the hash-pinned Strix executable is installed, the token-loading boundary installs a repository-owned launcher into the already validated Python scripts root and publishes its exact SHA-256 through `GITHUB_ENV`. The launcher accepts only `strix-agent==1.5.3`, replaces the module-local `asyncio` dependencies in `strix.interface.scan_setup` and `strix.interface.main` with a narrow proxy, and maps only non-positive `wait_for` deadlines to `None`. Positive deadlines and every other asyncio operation are delegated unchanged.

No provider route, fallback, retry, finding threshold, ZDR policy, dependency version, or total process budget changes. Noema and OpenCode do not receive the wrapper because the installer activates only when the Strix executable evidence is present.

## Removal condition

Remove the compatibility launcher when the pinned Strix release normalizes non-positive warm-up timeouts itself. Any Strix version change fails closed until that behavior and the two target module shapes are reviewed.

## Verification

The regression suite covers zero, negative, positive, and absent timeout values; exact-version and module-shape gates; atomic wrapper installation; executable-root and SHA-256 checks; symlink and mutable-root rejection; token-loader integration; and non-Strix consumer isolation. The new Python paths are held to the repository's 100% statement and branch coverage and 100% docstring requirements.
