# Sandboxed web readiness loopback boundary

## Decision

`sandboxed_web_e2e.py` polls only literal `localhost` or an IP address that
Python's standard-library `ipaddress` module classifies as loopback. Redirects
remain disabled. This supports the complete IPv4 loopback block, including
`127.0.0.2`, without admitting `0.0.0.0`, public addresses, link-local
metadata endpoints, or attacker-controlled DNS names.

The boundary uses the standard library rather than a second address table.
It therefore follows the runtime's maintained special-address definitions and
keeps one fail-closed validation point before any network request.

## Verification

The regression exercises literal `localhost`, `127.0.0.1`, another address in
`127.0.0.0/8`, an unspecified address, a `.localhost` subdomain, a public
hostname, and the common cloud metadata address. Only the literal name avoids
another DNS resolution boundary. The existing no-redirect test continues to
prove that an allowed readiness endpoint cannot redirect the poller across the
boundary.

## References

Internet Assigned Numbers Authority. (2026). *IANA IPv4 special-purpose
address registry*. Retrieved August 23, 2026, from
https://www.iana.org/assignments/iana-ipv4-special-registry/iana-ipv4-special-registry.xhtml

OWASP Foundation. (n.d.). *Server-side request forgery prevention cheat
sheet*. Retrieved August 23, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html

Python Software Foundation. (2026). *ipaddress — IPv4/IPv6 manipulation
library*. https://docs.python.org/3/library/ipaddress.html
