# Noema endpoint HTTPS and DNS fail-closed

## Incident and buyer impact

A credentialed Noema review request could leave the application after DNS
preflight ignored `socket.gaierror` or skipped malformed addresses. An
`http://` endpoint could also receive the API key without TLS. Shared
address space such as `100.64.0.1` is not `is_private` in Python and
previously crossed the guard.

## Decision

Accept only HTTPS. Fail before request construction on DNS error, empty
results, invalid IP strings, every non-global address (including RFC 6598
shared space), and multicast. Cap the response at 1 MiB. Do not log the
endpoint or credential. Organization egress policy and trusted DNS remain
required; this is defense in depth, not DNS-rebinding elimination.

## References

Rekhter, Y., Moskowitz, B., Karrenberg, D., de Groot, G. J., & Lear, E.
(1996). *Address allocation for private internets* (RFC 1918).
https://doi.org/10.17487/RFC1918

Weil, J., Kuarsingh, V., Donley, C., Liljenstolpe, C., & Azinger, M.
(2012). *IANA-reserved IPv4 prefix for shared address space* (RFC 6598).
https://doi.org/10.17487/RFC6598

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP
semantics* (RFC 9110). https://doi.org/10.17487/RFC9110
