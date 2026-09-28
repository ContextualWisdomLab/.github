#!/usr/bin/env bash
# Offline regression for bounded_gh_get.sh. No network access.
#
# Stop conditions tested independently:
#   first403     - HTTP 403 on first call  -> exit 75, 1 call
#   first429     - HTTP 429 on first call  -> exit 75, 1 call (429 independent)
#   rem0         - HTTP 200 but remaining=0 -> exit 75, 1 call (stop on quota)
#   second403    - 200 then 403            -> exit 75, 2 calls
# Domain-invariant tests:
#   traversal    - a dot-dot label must exit 2 before any gh call
#   slash/star/  - labels that are not a single safe filename stem exit 2
#     space/empty  before any gh call and write nothing outside OUTDIR
#   duplicate    - the second copy of a name exits 2 before a second gh call
set -u
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "${tmp:?}"' EXIT
mkdir "$tmp/bin"
cat > "$tmp/bin/gh" << 'MOCK'
#!/usr/bin/env bash
echo call >> "$GH_MOCK_LOG"
n=$(wc -l < "$GH_MOCK_LOG" | tr -d ' ')
case "$GH_MOCK_MODE" in
  first403)
    printf 'HTTP/2.0 403 Forbidden\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 42\r\nX-Ratelimit-Reset: 1789975342\r\nRetry-After: 60\r\n\r\n{"message":"API rate limit exceeded"}\n' "$n"
    exit 1 ;;
  first429)
    printf 'HTTP/2.0 429 Too Many Requests\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 42\r\nX-Ratelimit-Reset: 1789975342\r\nRetry-After: 60\r\n\r\n{"message":"Too many requests"}\n' "$n"
    exit 1 ;;
  rem0)
    printf 'HTTP/2.0 200 OK\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 0\r\nX-Ratelimit-Reset: 1789975342\r\n\r\n{}\n' "$n"
    ;;
  second403)
    if [ "$n" -ge 2 ]; then
      printf 'HTTP/2.0 403 Forbidden\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 0\r\nX-Ratelimit-Reset: 1789975342\r\nRetry-After: 60\r\n\r\n{"message":"API rate limit exceeded"}\n' "$n"
      exit 1
    fi
    printf 'HTTP/2.0 200 OK\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 42\r\n\r\n{}\n' "$n" ;;
  success)
    printf 'HTTP/2.0 200 OK\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 42\r\n\r\n{}\n' "$n" ;;
esac
MOCK
chmod +x "$tmp/bin/gh"
fail=0
check() { # mode expected_exit expected_calls expected_not_requested
  : > "$tmp/log"
  PATH="$tmp/bin:$PATH" GH_MOCK_LOG="$tmp/log" GH_MOCK_MODE=$1 \
    "$here/bounded_gh_get.sh" "$tmp/out-$1" a:x b:y c:z > /dev/null 2>&1; rc=$?
  calls=$(wc -l < "$tmp/log" | tr -d ' ')
  if [ "$rc" != "$2" ] || [ "$calls" != "$3" ] || ! grep -q 'reset_utc=2026-09-21T07:22:22Z' "$tmp/out-$1/STOP" \
     || ! grep -qx "not_requested=$4" "$tmp/out-$1/STOP"; then
    echo "FAIL mode=$1 rc=$rc calls=$calls"; fail=1
  else
    echo "ok mode=$1 rc=$rc calls=$calls"
  fi
}
check first403  75 1 "b:y c:z"   # HTTP 403 with remaining=42 stops; remaining is not the cause
check first429  75 1 "b:y c:z"   # HTTP 429 with remaining=42 stops on its own branch
check rem0      75 1 "b:y c:z"   # remaining=0 stops a HTTP 200 before later items
check second403 75 2 "c:z"       # 200 then 403 -> 2 calls, third never requested

: > "$tmp/log"
PATH="$tmp/bin:$PATH" GH_MOCK_LOG="$tmp/log" GH_MOCK_MODE=success \
  "$here/bounded_gh_get.sh" "$tmp/out-success" 'ok.name_1:api/one' b:y c:z > /dev/null 2>&1
rc_ok=$?
calls_ok=$(wc -l < "$tmp/log" | tr -d ' ')
if [ "$rc_ok" = 0 ] && [ "$calls_ok" = 3 ] && [ ! -f "$tmp/out-success/STOP" ] \
   && [ -f "$tmp/out-success/ok.name_1.raw" ]; then
  echo "ok success rc=$rc_ok calls=$calls_ok"
else
  echo "FAIL success rc=$rc_ok calls=$calls_ok (expected rc=0 calls=3 no-STOP)"; fail=1
fi

# Domain-invariant: an unsafe label must fail before any gh call and must not
# create a file outside the caller-supplied OUTDIR.
reject_label() { # tag label
  : > "$tmp/log"
  PATH="$tmp/bin:$PATH" GH_MOCK_LOG="$tmp/log" GH_MOCK_MODE=success \
    "$here/bounded_gh_get.sh" "$tmp/out-$1" "$2" > /dev/null 2>&1
  rc_label=$?
  calls_label=$(wc -l < "$tmp/log" | tr -d ' ')
  if [ "$rc_label" = 2 ] && [ "$calls_label" = 0 ] && [ ! -e "$tmp/out-$1/STOP" ] \
     && [ ! -e "$tmp/outside.raw" ]; then
    echo "ok reject $1 rc=$rc_label calls=$calls_label"
  else
    echo "FAIL reject $1 rc=$rc_label calls=$calls_label (expected rc=2 calls=0)"
    fail=1
  fi
}
reject_label traversal '../outside:api/path'
reject_label slash 'nested/evil:api/path'
reject_label dotdot '..:api/path'
reject_label star '*:api/path'
reject_label space 'a b:api/path'
reject_label empty ':api/path'

# Domain-invariant: duplicate name must fail without overwriting the first result.
# The first 'a:x' is legitimately fetched (1 call), then 'a:y' is rejected
# with exit 2 before it can overwrite a.raw — so calls=1, rc=2, no STOP file.
: > "$tmp/log"
PATH="$tmp/bin:$PATH" GH_MOCK_LOG="$tmp/log" GH_MOCK_MODE=success \
  "$here/bounded_gh_get.sh" "$tmp/out-dup" a:x a:y > /dev/null 2>&1; rc_dup=$?
calls_dup=$(wc -l < "$tmp/log" | tr -d ' ')
if [ "$rc_dup" = 2 ] && [ "$calls_dup" = 1 ] && [ ! -f "$tmp/out-dup/STOP" ]; then
  echo "ok duplicate rc=$rc_dup calls=$calls_dup (overwrite prevented, no STOP file)"
else
  echo "FAIL duplicate rc=$rc_dup calls=$calls_dup stop_exists=$([ -f "$tmp/out-dup/STOP" ] && echo yes || echo no) (expected rc=2 calls=1 no-STOP)"; fail=1
fi

exit $fail
