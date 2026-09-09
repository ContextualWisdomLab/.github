#!/usr/bin/env bash
set -euo pipefail

mark_unavailable() {
  echo "available=false" >>"$GITHUB_OUTPUT"
}

if [ "${USER_TOKEN_CONFIGURED:-false}" = "true" ]; then
  echo "A configured cross-repository user token takes precedence."
  mark_unavailable
  exit 0
fi
if [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ]; then
  echo "OpenCode app token exchange unavailable: OIDC request environment is missing."
  mark_unavailable
  exit 0
fi

request_url="$ACTIONS_ID_TOKEN_REQUEST_URL"
separator="?"
case "$request_url" in
  *\?*) separator="&" ;;
esac
if ! oidc_response="$(
  curl -fsS --connect-timeout 10 --max-time 30 \
    -H "Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
    "${request_url}${separator}audience=${OIDC_AUDIENCE}"
)"; then
  echo "OpenCode app token exchange unavailable: OIDC token request did not complete."
  mark_unavailable
  exit 0
fi
oidc_token="$(jq -r '.value // empty' <<<"$oidc_response")"
if [ -z "$oidc_token" ]; then
  echo "OpenCode app token exchange unavailable: OIDC token response was empty."
  mark_unavailable
  exit 0
fi
if ! token_response="$(
  curl -fsS --connect-timeout 10 --max-time 30 \
    -X POST \
    -H "Authorization: Bearer ${oidc_token}" \
    "${OPENCODE_API_BASE_URL}/exchange_github_app_token"
)"; then
  echo "OpenCode app token exchange unavailable: app token request did not complete."
  mark_unavailable
  exit 0
fi
app_token="$(jq -r '.token // empty' <<<"$token_response")"
if [ -z "$app_token" ]; then
  echo "OpenCode app token exchange unavailable: app token response was empty."
  mark_unavailable
  exit 0
fi
echo "::add-mask::$app_token"
echo "available=true" >>"$GITHUB_OUTPUT"
echo "OPENCODE_APP_TOKEN=$app_token" >>"$GITHUB_ENV"
