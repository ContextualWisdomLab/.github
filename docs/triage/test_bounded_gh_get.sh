#!/usr/bin/env bash
# Offline regression: a mocked first-response 403 (remaining 0) must stop the
# batch before any further gh call. No network access.
set -u
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "${tmp:?}"' EXIT
mkdir "$tmp/bin"
cat > "$tmp/bin/gh" <<'MOCK'
#!/usr/bin/env bash
echo call >> "$GH_MOCK_LOG"
n=$(wc -l < "$GH_MOCK_LOG" | tr -d ' ')
if [ "$GH_MOCK_MODE" = first403 ] || [ "$n" -ge 2 ]; then
  printf 'HTTP/2.0 403 Forbidden\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 0\r\nX-Ratelimit-Reset: 1789975342\r\nRetry-After: 60\r\n\r\n{"message":"API rate limit exceeded"}\n' "$n"
  exit 1
fi
printf 'HTTP/2.0 200 OK\r\nX-Github-Request-Id: MOCK:%s\r\nX-Ratelimit-Remaining: 42\r\n\r\n{}\n' "$n"
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
check first403 75 1 "b:y c:z"   # first response 403 -> 1 call, batch stopped
check second403 75 2 "c:z"  # 200 then 403 -> 2 calls, third never requested
exit $fail
