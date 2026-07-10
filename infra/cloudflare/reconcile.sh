#!/usr/bin/env bash
#
# reconcile.sh — idempotent Cloudflare DNS reconciler (curl + jq, no Terraform).
#
# Reads a declarative zones config (default: infra/cloudflare/zones.json) and,
# for each zone: ensures the zone exists in the Cloudflare account, upserts the
# declared DNS records, and prints the zone's Cloudflare-assigned nameservers and
# status so they can be set at the domain registrar (Namecheap).
#
# Secrets are taken from the environment (populated by GitHub Actions from the
# org secrets). Nothing secret is ever printed.
#
# Environment inputs:
#   CF_API_TOKEN   (required) Cloudflare API token       -> ${{ secrets.CLOUDFLARE_API_TOKEN }}
#   CF_ACCOUNT_ID  (required) Cloudflare account id       -> ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
#   CF_MODE        (optional) "dry-run" (default) | "apply"
#   CF_PRUNE       (optional) "true" to delete undeclared records | "false" (default)
#   CF_CONFIG      (optional) path to zones config (default infra/cloudflare/zones.json)
#
# Exit status: 0 on success (including fail-soft per-zone errors). Non-zero only
# when the API token itself cannot be verified, so a broken token is loud.

set -uo pipefail

CF_API="https://api.cloudflare.com/client/v4"
CF_MODE="${CF_MODE:-dry-run}"
CF_PRUNE="${CF_PRUNE:-false}"
CF_CONFIG="${CF_CONFIG:-infra/cloudflare/zones.json}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/null}"

zone_error_count=0

log()  { printf '%s\n' "$*"; }
sumln(){ printf '%s\n' "$*" >>"$SUMMARY"; }

require_env() {
  local missing=0
  [ -n "${CF_API_TOKEN:-}" ]  || { log "ERROR: CF_API_TOKEN is empty"; missing=1; }
  [ -n "${CF_ACCOUNT_ID:-}" ] || { log "ERROR: CF_ACCOUNT_ID is empty"; missing=1; }
  [ -f "$CF_CONFIG" ]         || { log "ERROR: config not found: $CF_CONFIG"; missing=1; }
  [ "$missing" -eq 0 ] || exit 2
}

# cf_api METHOD PATH [JSON_BODY] -> prints response body; sets global CF_HTTP
cf_api() {
  local method="$1" path="$2" body="${3:-}"
  local tmp http
  tmp="$(mktemp)"
  if [ -n "$body" ]; then
    http="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" "${CF_API}${path}" \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "$body")"
  else
    http="$(curl -sS -o "$tmp" -w '%{http_code}' -X "$method" "${CF_API}${path}" \
      -H "Authorization: Bearer ${CF_API_TOKEN}")"
  fi
  CF_HTTP="$http"
  cat "$tmp"
  rm -f "$tmp"
}

verify_token() {
  local resp ok
  resp="$(cf_api GET /user/tokens/verify)"
  ok="$(printf '%s' "$resp" | jq -r '.success // false')"
  if [ "$ok" = "true" ]; then
    log "TOKEN_STATUS: valid (Cloudflare API token verified)"
    return 0
  fi
  log "TOKEN_STATUS: INVALID — token verification failed (http ${CF_HTTP:-?})"
  log "$(printf '%s' "$resp" | jq -c '.errors // .' 2>/dev/null)"
  return 1
}

# Look up a zone by name inside the account. Echoes the zone result object (or empty).
get_zone() {
  local name="$1" resp
  resp="$(cf_api GET "/zones?name=${name}&account.id=${CF_ACCOUNT_ID}&status=all")"
  printf '%s' "$resp" | jq -c '.result[0] // empty'
}

create_zone() {
  local name="$1" resp
  local body
  body="$(jq -nc --arg n "$name" --arg a "$CF_ACCOUNT_ID" \
    '{name:$n, account:{id:$a}, type:"full"}')"
  resp="$(cf_api POST /zones "$body")"
  if [ "$(printf '%s' "$resp" | jq -r '.success // false')" = "true" ]; then
    printf '%s' "$resp" | jq -c '.result'
    return 0
  fi
  log "ERROR: failed to create zone ${name} (http ${CF_HTTP:-?}): $(printf '%s' "$resp" | jq -c '.errors // .')"
  return 1
}

# reconcile_records ZONE_ID ZONE_JSON
reconcile_records() {
  local zid="$1" zjson="$2"
  local count
  count="$(printf '%s' "$zjson" | jq '.records | length')"
  if [ "$count" -eq 0 ]; then
    log "  records: none declared (nothing to reconcile)"
    return 0
  fi

  # Track declared record identities for optional prune.
  local declared_ids="" existing_resp
  while IFS= read -r rec; do
    local rtype rname rcontent rproxied rttl rprio
    rtype="$(printf '%s' "$rec"    | jq -r '.record_type')"
    rname="$(printf '%s' "$rec"    | jq -r '.record_name')"
    rcontent="$(printf '%s' "$rec" | jq -r '.record_content')"
    rproxied="$(printf '%s' "$rec" | jq -r '.record_proxied // false')"
    rttl="$(printf '%s' "$rec"     | jq -r '.record_ttl // 1')"
    rprio="$(printf '%s' "$rec"    | jq -r '.record_priority // empty')"

    # Find an existing record of same type+name.
    existing_resp="$(cf_api GET "/zones/${zid}/dns_records?type=${rtype}&name=${rname}")"
    local rid
    rid="$(printf '%s' "$existing_resp" | jq -r '.result[0].id // empty')"

    # Build payload.
    local payload
    payload="$(jq -nc \
      --arg t "$rtype" --arg n "$rname" --arg c "$rcontent" \
      --argjson p "$rproxied" --argjson ttl "$rttl" \
      '{type:$t, name:$n, content:$c, proxied:$p, ttl:$ttl}')"
    if [ -n "$rprio" ]; then
      payload="$(printf '%s' "$payload" | jq -c --argjson pr "$rprio" '. + {priority:$pr}')"
    fi

    if [ -n "$rid" ]; then
      declared_ids="${declared_ids} ${rid}"
      if [ "$CF_MODE" = "apply" ]; then
        local up
        up="$(cf_api PUT "/zones/${zid}/dns_records/${rid}" "$payload")"
        if [ "$(printf '%s' "$up" | jq -r '.success // false')" = "true" ]; then
          log "  UPSERT ok: ${rtype} ${rname} -> ${rcontent} (updated)"
        else
          log "  ERROR upsert ${rtype} ${rname}: $(printf '%s' "$up" | jq -c '.errors // .')"
          zone_error_count=$((zone_error_count+1))
        fi
      else
        log "  [dry-run] would UPDATE ${rtype} ${rname} -> ${rcontent}"
      fi
    else
      if [ "$CF_MODE" = "apply" ]; then
        local cr crid
        cr="$(cf_api POST "/zones/${zid}/dns_records" "$payload")"
        if [ "$(printf '%s' "$cr" | jq -r '.success // false')" = "true" ]; then
          crid="$(printf '%s' "$cr" | jq -r '.result.id')"
          declared_ids="${declared_ids} ${crid}"
          log "  UPSERT ok: ${rtype} ${rname} -> ${rcontent} (created)"
        else
          log "  ERROR create ${rtype} ${rname}: $(printf '%s' "$cr" | jq -c '.errors // .')"
          zone_error_count=$((zone_error_count+1))
        fi
      else
        log "  [dry-run] would CREATE ${rtype} ${rname} -> ${rcontent}"
      fi
    fi
  done < <(printf '%s' "$zjson" | jq -c '.records[]')

  # Optional prune of undeclared records.
  if [ "$CF_PRUNE" = "true" ]; then
    local all_ids
    all_ids="$(cf_api GET "/zones/${zid}/dns_records?per_page=100" | jq -r '.result[].id')"
    local id
    for id in $all_ids; do
      case " $declared_ids " in
        *" $id "*) : ;;
        *)
          if [ "$CF_MODE" = "apply" ]; then
            cf_api DELETE "/zones/${zid}/dns_records/${id}" >/dev/null
            log "  PRUNE: deleted undeclared record ${id}"
          else
            log "  [dry-run] would PRUNE undeclared record ${id}"
          fi
          ;;
      esac
    done
  fi
}

main() {
  require_env

  log "=== Cloudflare DNS reconcile ==="
  log "mode=${CF_MODE}  prune=${CF_PRUNE}  config=${CF_CONFIG}"
  log ""

  if ! verify_token; then
    log "Aborting: cannot proceed without a valid API token."
    exit 1
  fi

  sumln "## Cloudflare DNS reconcile"
  sumln ""
  sumln "**Mode:** \`${CF_MODE}\`  **Prune:** \`${CF_PRUNE}\`"
  sumln ""
  sumln "Point these nameservers at Namecheap for each domain. A zone stays **pending** until Namecheap delegation propagates, then flips to **active**."
  sumln ""
  sumln "| Domain | Product repo | Zone status | Cloudflare nameservers |"
  sumln "| ------ | ------------ | ----------- | ---------------------- |"

  local zcount
  zcount="$(jq '.zones | length' "$CF_CONFIG")"
  log "Discovered ${zcount} zone(s) in config."
  log ""

  local i
  for i in $(seq 0 $((zcount-1))); do
    local zjson zname prepo plabel
    zjson="$(jq -c ".zones[$i]" "$CF_CONFIG")"
    zname="$(printf '%s' "$zjson"  | jq -r '.zone_name')"
    prepo="$(printf '%s' "$zjson"  | jq -r '.product_repo')"
    plabel="$(printf '%s' "$zjson" | jq -r '.product_label')"

    log "--- zone: ${zname} (${plabel} / ${prepo}) ---"

    local zobj zid zstatus zns
    zobj="$(get_zone "$zname")"

    if [ -z "$zobj" ]; then
      if [ "$CF_MODE" = "apply" ]; then
        log "  zone not found; creating..."
        zobj="$(create_zone "$zname")" || { zone_error_count=$((zone_error_count+1)); }
      fi
    fi

    if [ -z "$zobj" ]; then
      # Still no zone object (dry-run and not existing, or create failed).
      if [ "$CF_MODE" = "dry-run" ]; then
        log "  zone does NOT exist yet. In apply mode it will be created via POST /zones,"
        log "  and Cloudflare will then assign nameservers (reported on the apply run)."
        printf 'NAMESERVERS|%s|not-created(dry-run)|%s\n' "$zname" "apply-mode-will-create-and-report"
        sumln "| ${zname} | ${prepo} | _not created (dry-run)_ | _apply mode will create & report_ |"
      else
        log "  zone could not be resolved or created; see errors above."
        printf 'NAMESERVERS|%s|error|unavailable\n' "$zname"
        sumln "| ${zname} | ${prepo} | error | unavailable |"
        zone_error_count=$((zone_error_count+1))
      fi
      log ""
      continue
    fi

    zid="$(printf '%s' "$zobj"     | jq -r '.id')"
    zstatus="$(printf '%s' "$zobj" | jq -r '.status')"
    zns="$(printf '%s' "$zobj"     | jq -r '(.name_servers // []) | join(", ")')"
    [ -n "$zns" ] || zns="(not assigned yet)"

    log "  zone id: ${zid}"
    log "  status : ${zstatus}"
    log "  nameservers: ${zns}"
    # Machine-parseable line for log scraping:
    printf 'NAMESERVERS|%s|%s|%s\n' "$zname" "$zstatus" "$zns"
    sumln "| ${zname} | ${prepo} | ${zstatus} | ${zns} |"

    reconcile_records "$zid" "$zjson"
    log ""
  done

  sumln ""
  if [ "$CF_MODE" = "dry-run" ]; then
    sumln "> Dry-run: no changes were written. Re-run with \`mode=apply\` to create zones and records."
  fi
  if [ "$zone_error_count" -gt 0 ]; then
    log "Completed with ${zone_error_count} non-fatal zone/record error(s) (fail-soft)."
  else
    log "Completed with no errors."
  fi
  exit 0
}

main "$@"
