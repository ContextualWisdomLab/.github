#!/usr/bin/env bash
# Bounded one-shot REST GETs for the shared-account CI lane.
#
# Usage: bounded_gh_get.sh OUTDIR name:api/path [name:api/path ...]
#
# One GET per item, in order. The WHOLE batch stops (exit 75) at the first
# response that is HTTP 403/429 or reports X-RateLimit-Remaining: 0, after
# saving that response and its reset/Retry-After headers to OUTDIR/STOP.
# Items after the stop are never requested. Do not retry, loop, or switch to
# another API (e.g. GraphQL) to get around an exhausted quota; wait until
# the recorded reset time.
set -u
out=$1; shift
mkdir -p "$out"
hdr() { grep -i "^$1:" "$2" | head -1 | cut -d: -f2- | tr -d ' \r'; }
while [ "$#" -gt 0 ]; do
  item=$1; shift
  name=${item%%:*}; path=${item#*:}
  gh api -i "$path" > "$out/$name.raw" 2> "$out/$name.err"; rc=$?
  status=$(head -1 "$out/$name.raw" | awk '{print $2}')
  rem=$(hdr x-ratelimit-remaining "$out/$name.raw")
  reset=$(hdr x-ratelimit-reset "$out/$name.raw")
  retry=$(hdr retry-after "$out/$name.raw")
  req=$(hdr x-github-request-id "$out/$name.raw")
  line="$name http=${status:-none} rc=$rc req=${req:-none} remaining=${rem:-none} reset=${reset:-none} retry_after=${retry:-none}"
  echo "$line"
  if [ "$status" = 403 ] || [ "$status" = 429 ] || [ "$rem" = 0 ]; then
    reset_utc=$( [ -n "$reset" ] && date -u -r "$reset" +%FT%TZ 2>/dev/null || date -u -d "@$reset" +%FT%TZ 2>/dev/null || echo none)
    printf '%s\nnot_requested=%s\nreset_utc=%s\n' "$line" "$*" "$reset_utc" > "$out/STOP"
    echo "STOP: quota/limit response on $name; reset_utc=$reset_utc retry_after=${retry:-none}; remaining items not requested" >&2
    exit 75
  fi
  if [ "$rc" -ne 0 ]; then
    echo "STOP: non-success on $name (rc=$rc)" >&2
    exit 1
  fi
done
