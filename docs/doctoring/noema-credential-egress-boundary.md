# Noema credential-egress boundary

## Customer outcome

Noema now rejects a misconfigured or attacker-influenced model endpoint before
placing its bearer credential on the request. A public service must use HTTPS,
must resolve entirely to globally routable unicast addresses, and must retain
the same complete DNS address set after the bounded response is received.
Resolver failures, empty answers, malformed addresses, redirects, special-use
addresses, and response bodies larger than 1 MiB fail closed.

The existing same-job contextual-orchestrator seam remains usable without
importing the orchestrator into this repository: literal `127.0.0.1` and `::1`
endpoints may use HTTP only when every resolver result is loopback. Hostnames
that merely resolve to loopback do not receive this exception. Provider routing,
model selection, and model-parameter translation remain upstream concerns.

## Decision and trust boundary

The implementation reuses Python's `urllib.parse`, `socket.getaddrinfo`, and
`ipaddress` rather than adding a URL or address-classification dependency.
Before request construction it:

1. rejects non-HTTP schemes, URL user information, and missing hostnames;
2. restricts plaintext HTTP to the two literal loopback sidecar addresses;
3. resolves the endpoint for its effective port and rejects failed, empty, or
   malformed resolution evidence; and
4. requires every non-loopback address to be globally routable unicast.

Redirects remain disabled, and the opener disables ambient proxies. Custom HTTP
and HTTPS connections connect only to the validated numeric addresses while
retaining the original hostname for HTTPS certificate validation. The response
reader requests at most one byte beyond the 1 MiB contract, rejects an
over-limit result before decoding JSON, and then re-resolves the same host and
port. A changed address set invalidates the result. Tests cover IPv4 and IPv6
loopback, dual-stack public endpoints, pinned numeric TCP destinations, TLS SNI,
DNS rebinding evidence, resolver failures, malformed results, URL credentials,
special-use address classes, and the byte limit.

Trusted DNS and network egress controls remain defense-in-depth for production;
the application boundary now also prevents the request socket from performing
an unvalidated hostname resolution.

## References

Cotton, M., Vegoda, L., Bonica, R., & Haberman, B. (2013). *Special-purpose IP
address registries* (RFC 6890). RFC Editor. https://doi.org/10.17487/RFC6890

MITRE. (2026a). *CWE-400: Uncontrolled resource consumption*.
https://cwe.mitre.org/data/definitions/400.html

MITRE. (2026b). *CWE-918: Server-side request forgery (SSRF)*.
https://cwe.mitre.org/data/definitions/918.html

OWASP Foundation. (n.d.). *Server-side request forgery prevention cheat sheet*.
Retrieved August 24, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
