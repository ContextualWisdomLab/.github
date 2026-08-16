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
| Cursor Cloud Agent | Figma personal or plan access token in `FIGMA_ACCESS_TOKEN` | REST only (`X-Figma-Token` on `https://api.figma.com/v1/...`) |

A personal or plan access token does **not** unlock Figma MCP on Cloud Agents.
It only authorizes the REST API. Do not commit the token. Do not put it in
`environment.json`, workflow YAML, or chat output.

Prefer a **plan access token** for organization CI and Cloud Agent fleets
(admin-managed, not tied to one person, expiry up to one year; Figma, n.d.-a).
Use a personal access token only when the operator is acting on their own
account (maximum 90 days). Both kinds are stored in the same secret name.

Whoami is not enough for design-to-code. After the secret is present, load one
file at `GET /v1/files/:key?depth=1` so the next action is a named page, node,
or image request rather than downloading the entire document tree (Figma,
n.d.-c). File keys are the `:file_key` segment from
`https://www.figma.com/:file_type/:file_key/:file_name` and must be 8–128
alphanumeric characters (CWE-22 path-restriction; MITRE, 2026). The helper
sends only `X-Figma-Token`, pins `http.client.HTTPSConnection("api.figma.com")`,
and caps whoami bodies at 64 KiB and file bodies at 8 MiB (RFC 9110 message
framing; Fielding et al., 2022).

## Operator procedure

1. **Desktop / CLI MCP (preferred for design-to-code).** In Cursor Desktop,
   Settings → Tools & MCP → Figma → Connect, then Allow access in the Figma
   browser window. Confirm with a Figma MCP `whoami` from a desktop agent.
2. **Cloud Agent REST secret.** In Figma: account menu → Settings → Security
   → Personal access tokens → Generate new token, or ask a plan admin for a
   plan access token. Grant `file_content:read` (add comment scopes only if
   needed). Store the value as the Cursor environment secret
   `FIGMA_ACCESS_TOKEN`.
3. **Verify the secret without printing it:**

   ```bash
   python3 scripts/ci/figma_rest_auth.py
   ```

   Success prints a handle/id/email line. Missing or rejected tokens exit
   non-zero and never echo the secret.
4. **Load the file the buyer asked for** (copy the key from the Figma URL):

   ```bash
   python3 scripts/ci/figma_rest_auth.py --file FILE_KEY
   ```

   Success prints page names plus component and style counts. Next: request
   that page's node JSON or images over REST. The helper opens a pinned
   `http.client.HTTPSConnection("api.figma.com")` and refuses any other URL,
   so Semgrep `dynamic-urllib-use-detected` does not apply
   (`urllib.request.urlopen` is not used).

## Why MCP Connect cannot be finished here

Figma only accepts MCP clients listed in its catalog (Figma, n.d.-d). The
Cloud Agent MCP client is not on that list, so the OAuth authorize endpoint
answers `Forbidden` / `401` before a browser grant can be created. Asking the
user to "click Connect" inside a Cloud Agent or Automation therefore cannot
succeed. The same Connect button works in the desktop IDE because that client
is allowlisted.

## References (APA 7th edition)

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Figma. (n.d.-a). *Authentication*. Figma Developer Docs. Retrieved August 16,
2026, from https://developers.figma.com/docs/rest-api/authentication/

Figma. (n.d.-b). *Personal access tokens*. Figma Developer Docs. Retrieved
August 16, 2026, from
https://developers.figma.com/docs/rest-api/personal-access-tokens/

Figma. (n.d.-c). *Files*. Figma Developer Docs. Retrieved August 16, 2026,
from https://developers.figma.com/docs/rest-api/file-endpoints/

Figma. (n.d.-d). *Set up the remote server (recommended)*. Figma Developer
Docs. Retrieved August 16, 2026, from
https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/

Figma. (n.d.-e). *Changelog*. Figma Developer Docs. Retrieved August 16, 2026,
from https://developers.figma.com/docs/rest-api/changelog/

MITRE. (2026). *CWE-22: Improper limitation of a pathname to a restricted
directory ('Path Traversal')*. https://cwe.mitre.org/data/definitions/22.html

Neilson, K. (2026, June 10). Reply in *Figma MCP shows "Forbidden" in
Automations / Cloud Agents*. Cursor Forum.
https://forum.cursor.com/t/figma-mcp-shows-forbidden-in-automations-cloud-agents/162969

Parecki, A., Hardt, D., & Lodderstedt, T. (2025). *The OAuth 2.1 authorization
framework* (Internet-Draft). Internet Engineering Task Force.
https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1

Sakimura, N., Bradley, J., & Agarwal, N. (2015). *Proof Key for Code Exchange
by OAuth public clients* (RFC 7636). RFC Editor.
https://doi.org/10.17487/RFC7636
