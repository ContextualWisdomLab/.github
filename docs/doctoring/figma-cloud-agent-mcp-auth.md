# Figma MCP auth on Cursor Cloud Agents

## Incident

A Cursor Cloud Agent tasked with Figma work discovers the official Figma MCP
server (`https://mcp.figma.com/mcp`) in an `error` state: live tool discovery
fails and no Figma tools are available. Re-running Connect / OAuth from the
Cloud Agent cannot repair it. Desktop Cursor and the Cursor CLI remain able to
complete the same OAuth flow.

## Live evidence (2026-08-16)

Unauthenticated `initialize` against the remote MCP endpoint:

```http
POST https://mcp.figma.com/mcp
HTTP/2 401
WWW-Authenticate: Bearer resource_metadata="https://mcp.figma.com/.well-known/oauth-protected-resource",scope="mcp:connect",authorization_uri="https://api.figma.com/.well-known/oauth-authorization-server"
```

Body: `Unauthorized`.

The same environment can reach Figma (`HEAD`/`POST` complete; no egress block).
`GET https://api.figma.com/v1/me` without a token returns
`{"status":403,"err":"Invalid token"}`. No `FIGMA_*` environment variables are
present on the Cloud Agent VM.

Figma's remote MCP is OAuth 2.1 with PKCE and an allowlisted MCP client
catalog. Cursor Cloud Agents are not a supported client for that catalog.

## Decision

Do not treat Figma MCP as available inside Cloud Agents or Cloud Automations.
Cursor staff stated this explicitly: Figma MCP is not supported in Cloud agents;
it is fully supported in the IDE and the CLI (Neilson, 2026). There is no
estimated timeline; support is a joint Cursor/Figma change.

Use two disjoint auth paths:

| Surface | Auth | Capability |
|---|---|---|
| Cursor Desktop / CLI | Figma MCP OAuth (`Settings → Tools & MCP → Figma → Connect`) | Full MCP toolset (`get_design_context`, `use_figma`, write-to-canvas, …) |
| Cursor Cloud Agent | Figma personal access token in `FIGMA_ACCESS_TOKEN` | REST only (`X-Figma-Token` on `https://api.figma.com/v1/...`) |

A personal access token does **not** unlock Figma MCP on Cloud Agents. It only
authorizes the REST API. Do not commit the token. Do not put it in
`environment.json`, workflow YAML, or chat output.

## Operator procedure

1. **Desktop / CLI MCP (preferred for design-to-code).** In Cursor Desktop,
   Settings → Tools & MCP → Figma → Connect, then Allow access in the Figma
   browser window. Confirm with a Figma MCP `whoami` from a desktop agent.
2. **Cloud Agent REST fallback.** In Figma: account menu → Settings → Security
   → Personal access tokens → Generate new token. Name it for Cloud Agents.
   Grant `file_content:read` (add comment scopes only if needed). Maximum
   expiry is 90 days (Figma, 2025). Store the value as the Cursor environment
   secret `FIGMA_ACCESS_TOKEN`.
3. **Verify the secret without printing it:**

   ```bash
   python3 scripts/ci/figma_rest_auth.py
   ```

   Success prints a handle/id/email line. Missing or rejected tokens exit
   non-zero and never echo the secret.

## Why MCP Connect cannot be finished here

Figma only accepts MCP clients listed in its catalog (Figma, 2026b). The
Cloud Agent MCP client is not on that list, so the OAuth authorize endpoint
answers `Forbidden` / `401` before a browser grant can be created. Asking the
user to "click Connect" inside a Cloud Agent or Automation therefore cannot
succeed. The same Connect button works in the desktop IDE because that client
is allowlisted.

## References

Figma. (2025). *Changelog*. Figma Developer Docs.
https://developers.figma.com/docs/rest-api/changelog/

Figma. (2026a). *Personal access tokens*. Figma Developer Docs.
https://developers.figma.com/docs/rest-api/personal-access-tokens/

Figma. (2026b). *Set up the remote server (recommended)*. Figma Developer Docs.
https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/

Neilson, K. (2026, June 10). Reply in *Figma MCP shows "Forbidden" in
Automations / Cloud Agents*. Cursor Forum.
https://forum.cursor.com/t/figma-mcp-shows-forbidden-in-automations-cloud-agents/162969
