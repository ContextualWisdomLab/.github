# Orca worker GitHub token bootstrap (App-first, fail-closed)

## Incident and root cause

Orca leads and workers share one human OAuth token at
`~/.config/orca-workers/gh-token` (user id `8172694`, 5000 REST requests/hour).
Concurrent GraphQL/REST polling exhausts that single bucket and blocks every
lead. GitHub App installation tokens (`ghs_…`) use a separate rate-limit
bucket per installation and must be preferred for org work.

## Live installation evidence (2026-09-18)

Queried once via `GET /orgs/ContextualWisdomLab/installations` and cached under
`/tmp/cwl-app-installations-summary.json` (do not re-poll while core remaining
is low; wait for `X-RateLimit-Reset`).

| Field | Value |
| --- | --- |
| App slug | `cwl-noema-review` |
| App id | `4291520` (matches org Actions var `NOEMA_GITHUB_APP_ID`) |
| Installation id | `146401636` |
| Account | `ContextualWisdomLab` |
| `repository_selection` | `all` (entire org; ~80 repositories at measurement) |
| Permissions | `actions`, `checks`, `contents`, `issues`, `metadata`, `pull_requests`, `security_events`, `statuses`, `vulnerability_alerts` |

Org Actions vars also expose public client metadata
`NOEMA_GITHUB_APP_CLIENT_ID` / `NOEMA_GITHUB_APP_ID`. Private keys and
installation tokens must never enter this repository.

## Can workers mint tokens through Noema today?

**No.** The deployed Noema Cloudflare Worker broker accepts only GitHub
Actions OIDC:

| Contract | Value |
| --- | --- |
| Endpoint | `POST /exchange` (`NOEMA_TOKEN_EXCHANGE_URL` / `NOEMA_EXCHANGE_URL`) |
| Issuer | `https://token.actions.githubusercontent.com` |
| Audience | `cwl-noema-review` |
| Trusted workflow (exact) | `ContextualWisdomLab/.github/.github/workflows/noema-review.yml@refs/heads/main` |
| Body | `{ "target_repository": "ContextualWisdomLab/<repo>" }` |
| Success | short-lived installation token in the JSON envelope |

Central CI call path (trusted base branch of `.github`):

1. Job requests an Actions ID token with audience `cwl-noema-review`
   (see `.github/workflows/noema-review.yml` step `Exchange Noema app token through OIDC`).
2. `curl` `POST`s that JWT to `${NOEMA_TOKEN_EXCHANGE_URL}` with
   `target_repository`.
3. Worker verifies RS256/JWKS, issuer, audience, owner, exact workflow ref,
   and single-use `jti`, then returns a repository-scoped App token.

Preferred CI path when org secrets are present: mint directly with
`actions/create-github-app-token` using `NOEMA_GITHUB_APP_CLIENT_ID` +
`NOEMA_GITHUB_APP_PRIVATE_KEY` (same App), still inside Actions — not from an
Orca terminal.

Orca workers have neither `ACTIONS_ID_TOKEN_REQUEST_*` nor the App private
key, so they cannot call `/exchange` and must not attempt to. Extending Noema
with a non-Actions worker credential is a separate product change.

## `~/.config/orca-workers/` convention (secrets stay local)

Never commit these files. Mode `0600` on token files; never print values.

| Path | Role |
| --- | --- |
| `gh-token` | Shared human OAuth/PAT fallback (`gho_` / `ghp_` / fine-grained). Last resort. |
| `gh-token-app` | Preferred short-lived `cwl-noema-review` installation token (`ghs_`). |
| `gh-token-app.meta.json` | Non-secret metadata: `app_slug`, `installation_id`, `expires_at`, `minted_at`, `repositories` (optional). |
| `cache/` | Durable GraphQL/REST response cache keyed by request fingerprint. |
| `rate-limit.json` | Last observed `remaining` / `reset` / `resource` for the active token class. |

Operator mint (outside the worker, with App PEM held only in a local
capability path such as `~/.config/orca-workers/noema-app.pem` — never in git):

```bash
# Example only: use actions/create-github-app-token locally, or GitHub's
# App JWT → POST /app/installations/146401636/access_tokens with minimal
# repository permissions. Write the token to gh-token-app and expires_at
# to gh-token-app.meta.json. Rotate before expiry.
```

Workers then run `scripts/orca/export_github_token.sh` (or source it) which:

1. Prefers a non-expired `gh-token-app`.
2. Otherwise falls back to `gh-token` only after recording a warning.
3. On HTTP 403/429 with rate-limit headers: writes `rate-limit.json`, sleeps
   until `reset` (no busy re-poll), and exits non-zero if still exhausted.
4. Exports `GH_TOKEN` / `GITHUB_TOKEN` for the child process only.

## GraphQL / REST discipline (binding for workers)

- Prefer GraphQL for org/repo discovery; cache under
  `~/.config/orca-workers/cache/` with an explicit TTL.
- On any 403/429, read `X-RateLimit-Reset` / GraphQL `rateLimit.resetAt` and
  **sleep until that instant**. Do not spin `gh api` / `gh search` loops.
- Treat `gh api rate_limit` as advisory; honor the headers on the failing
  call when they disagree.
- One installation summary or org-repo sample per task is enough evidence;
  subsequent steps must reuse the cache file.
- Secondary rate limits still require backoff even when primary `remaining`
  looks healthy.

## Acceptance snapshot for this doctoring record

1. `cwl-noema-review` is installed on `ContextualWisdomLab` with
   `repository_selection=all`.
2. Worker → Noema `/exchange` is unavailable without Actions OIDC; CI paths
   are documented above.
3. Local App-first file convention + `scripts/orca/export_github_token.sh`
   replace silent shared-PAT burn.
4. Cache + reset-backoff rules above are mandatory for Orca workers.
