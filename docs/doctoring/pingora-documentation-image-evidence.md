# Pingora documentation image evidence

The required Pingora gate previously sent a changed PNG screenshot through its
UTF-8 runtime-content decoder because GitHub omits text patches for binary files.
That rejected UI evidence before the policy could determine whether it described
an active edge runtime.

ADR-0019 now admits documentation PNG screenshots only when the bounded final
file is a complete CRC-valid PNG chunk stream ending at IEND with no trailing
payload, conforming chunk names and palette bounds, and bounded null- or
Adam7-interlaced decompressed scanlines that match IHDR. A signature or
CRC-valid arbitrary IDAT is insufficient. Files in a runtime path, malformed signatures,
unsupported binary formats, and unavailable evidence continue to fail closed.
The gate establishes bounded binary evidence rather than general image-rendering
fidelity; optional ancillary-chunk semantics are outside this policy boundary.
`tests/test_pingora_edge_policy.py` covers the accepted PNG and the existing fake
PDF/runtime cases; targeted branch coverage remains 100%.
