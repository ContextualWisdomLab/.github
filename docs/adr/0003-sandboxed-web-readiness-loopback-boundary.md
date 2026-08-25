# ADR-0003: Sandboxed web readiness loopback boundary

- Status: accepted
- Date: 2026-08-25
- Scope: ContextualWisdomLab/.github control-plane E2E sandbox
- Decision: Poll `--backend-ready-url` and `--frontend-ready-url` only after the URL is proven to be HTTP(S) loopback. Accept literal `localhost` or a standard-library loopback address, unwrap IPv4-mapped IPv6, reject userinfo and missing hosts, and keep redirects disabled.
- Ownership: `.github` owns the sandbox helper. Product repositories keep pointing readiness at their own loopback services.
- Figma File ID: N/A. This repository has no customer UI.
- Consequence: A review run cannot use the sandbox poller as an SSRF trampoline to metadata services or public hosts. Operators fix a rejected URL by pointing it at `127.0.0.1` or `::1`. Papers live in `docs/doctoring/sandboxed-web-readiness-loopback-boundary.md`.
