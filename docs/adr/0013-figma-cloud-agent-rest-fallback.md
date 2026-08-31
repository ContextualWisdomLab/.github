# ADR 0013: Figma Cloud-Agent REST fallback

- Status: Accepted
- Date: 2026-08-20
- Owners: ContextualWisdomLab `.github` automation
- Figma File ID: N/A — this repository change is a security and API
  integration helper, not a user-facing canvas or component design.

## Context

The Figma MCP OAuth flow is available to supported desktop and CLI clients,
but a Cloud Agent cannot complete that client registration. The automation
still needs a bounded way to inspect a buyer-supplied Figma file without
printing credentials or accepting an arbitrary URL.

## Decision

Keep desktop and CLI agents on Figma MCP. Cloud Agents use
`FIGMA_ACCESS_TOKEN` with the repository's pinned REST helpers. The helpers
pin the Figma HTTPS origin, allowlist file and node identifiers, cap response
bodies, and emit token-free outlines. No design artifact is introduced by
this infrastructure PR, which is why the Figma File ID is explicitly N/A.

## Verification and rollback

Run `pytest -q tests/test_figma_rest_auth.py tests/test_figma_rest_file.py`.
Rollback by reverting the helper and its caller documentation; desktop/CLI
MCP remains independent.

## APA 7th references

Figma. (2026). *File endpoints*. Figma Developer Docs. Retrieved August 20,
2026, from https://developers.figma.com/docs/rest-api/file-endpoints/

Figma. (2026). *Set up the remote server*. Figma Developer Docs. Retrieved
August 20, 2026, from
https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force.
https://www.rfc-editor.org/rfc/rfc9110
