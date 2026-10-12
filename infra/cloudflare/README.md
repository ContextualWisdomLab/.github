# Cloudflare DNS + Pages (infrastructure as code)

This directory manages the org's domains and static hosting on **Cloudflare**,
declaratively, with nothing more than `curl` + `jq` running inside GitHub
Actions. No Terraform — six zones do not justify the moving parts.

## The model

- **Cloudflare is the DNS authority _and_ the host.** Each domain becomes a
  Cloudflare *zone*; static marketing sites are served from **Cloudflare Pages**
  (Workers can be added later the same way).
- **Namecheap only holds the registration.** After a zone is created in
  Cloudflare, you do a **one-time** step at Namecheap: replace the default
  Namecheap nameservers with the two nameservers Cloudflare assigns to that
  zone. From then on, all records are managed here in `zones.json`.
- **The Cloudflare API token is never exposed to pull request code.** It lives
  as the org secret `CLOUDFLARE_API_TOKEN` (with `CLOUDFLARE_ACCOUNT_ID`). Pull
  requests validate `zones.json` offline. Only trusted `main` pushes and manual
  workflow runs touch the Cloudflare API with
  `${{ secrets.CLOUDFLARE_API_TOKEN }}` / `${{ secrets.CLOUDFLARE_ACCOUNT_ID }}`.

## Files

| File | Purpose |
| ---- | ------- |
| `zones.json` | Declarative list of the 6 zones + their DNS records (data-driven; records start empty). |
| `reconcile.sh` | Idempotent reconciler (curl + jq). Ensures zones exist, upserts records, prints nameservers. |
| `../../.github/workflows/cloudflare-dns.yml` | Runs `reconcile.sh` with the org secrets. Dry-run by default. |
| `../../.github/workflows/deploy-pages.yml` | Reusable (`workflow_call`) Cloudflare Pages deploy any product repo can call. |

## Domain ↔ product map

| Domain | Product repo | Product |
| ------ | ------------ | ------- |
| `keyverse.io` | `cwl-idp` | Keyverse |
| `wardnet.io` | `waf-ids-ai-soc` | Wardnet |
| `inkspan.io` | `cwl-editor` | Inkspan |
| `cloud-erd.app` | `pg-erd-cloud` | Cloud ERD |
| `naruon.net` | `naruon` | Naruon |
| `naruon.io` | `naruon` | Naruon |

## One-time setup per domain (Namecheap → Cloudflare)

1. **Create the zone + read its nameservers.** Run the `Cloudflare DNS`
   workflow in **apply** mode (Actions tab → *Cloudflare DNS* →
   *Run workflow* → `mode = apply`). For any zone that does not exist yet, it
   creates it via `POST /zones` and prints the two assigned nameservers and the
   zone status to the job summary (and the run log).
2. **Point Namecheap at Cloudflare.** In Namecheap → *Domain List* → *Manage* →
   *Nameservers* → **Custom DNS**, enter the two Cloudflare nameservers reported
   for that domain, and save.
3. **Wait for activation.** The zone status is `pending` until Namecheap
   delegation propagates (minutes to a few hours), then flips to `active`.
   Re-running the workflow re-prints the current status.

## Adding DNS records (once a Pages project exists)

Records are intentionally empty for now because the Pages hosting targets do not
exist yet. To add one, edit `zones.json` and append to the target zone's
`records` array using this shape:

```json
{
  "record_type": "CNAME",
  "record_name": "keyverse.io",
  "record_content": "keyverse-marketing.pages.dev",
  "record_proxied": true,
  "record_ttl": 1
}
```

Then either push to `main` (the workflow runs a **dry-run** automatically) or
run the workflow manually with `mode = apply`. Reconciliation is idempotent:
existing records are updated in place, missing ones are created. Nothing is
deleted unless you explicitly set `prune = true`.

## Deploying a product's static site to Cloudflare Pages

Product repos call the reusable workflow and explicitly map the two declared
Cloudflare secret names:

```yaml
# .github/workflows/site.yml in e.g. cwl-idp (Keyverse)
name: Publish marketing site
on:
  push:
    branches: [main]
jobs:
  deploy:
    uses: ContextualWisdomLab/.github/.github/workflows/deploy-pages.yml@main
    with:
      project_name: keyverse-marketing
      build_dir: ./public
      custom_domain: keyverse.io   # optional; the CF zone must already exist
    secrets:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

Approved CWL callers MUST keep these explicit mappings and MUST NOT use
`secrets: inherit`; see
[the reusable-workflow secret contract](../../docs/doctoring/deploy-pages-secret-contract.md).

The reusable workflow publishes `build_dir` to the named Pages project (creating
it on first run) via `wrangler pages deploy`, then idempotently attaches
`custom_domain` if provided. After attaching a custom domain, add the matching
DNS record to `zones.json` (usually a proxied `CNAME` to `<project>.pages.dev`)
so the apex/`www` resolves to the site.

This same reusable workflow is the deploy path for the per-product marketing
pages and for the org `github.io` / profile content.

## Safety notes

- **Dry-run is the default.** Pull requests run offline config validation,
  `workflow_dispatch` defaults to `mode = dry-run`, and `push` events are
  always dry-run — only an explicit manual run with `mode = apply` writes to
  Cloudflare.
- **No destructive deletes** unless `prune = true` is set explicitly.
- **Fail-soft:** per-zone/record errors are logged and the run continues. Main
  push dry-runs also log and skip invalid or unavailable Cloudflare credentials
  so secret rotation does not block unrelated central governance merges. Manual
  `mode = apply` still hard-fails on missing or invalid credentials.
