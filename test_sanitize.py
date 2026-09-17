from scripts.ci.sanitize_contextual_orchestrator_sidecar_stream import sanitize_line
lines = [
    "provider_discovery_failed provider=bytez code=http_status_500",
    "2026-09-09 21:41:41.2276107Z [contextual-orchestrator-sidecar] sidecar startup warnings (non-fatal): provider_discovery_failed provider=bytez code=http_status_500",
]
for line in lines:
    print(repr(sanitize_line(line)))
