def _truthy_env(name: str) -> bool:
    """Return whether a process environment flag is an explicit truthy value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_literal_host(hostname: str) -> bool:
    """Return whether hostname is the sidecar loopback literal 127.0.0.1 or ::1."""
    return hostname in ORCHESTRATOR_LOOPBACK_HOSTS


def _http_origin(parsed: urllib.parse.ParseResult) -> tuple[str, str, int] | None:
    """Return scheme, hostname, and port for a credential-free http(s) URL."""
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return (scheme, hostname, port)


def is_allowed_orchestrator_sidecar_url(api_url: str) -> bool:
    """Return True only for the process-local orchestrator sidecar loopback origin.

    ``localhost`` and other private hosts stay rejected. A loopback literal
    (``127.0.0.1`` / ``::1``) is allowed only when it matches
    ``CONTEXTUAL_ORCHESTRATOR_BASE_URL`` or when ``NOEMA_LLM_VIA_ORCHESTRATOR``
    is an explicit truthy flag.
    """
    origin = _http_origin(urllib.parse.urlparse(api_url))
    if origin is None:
        return False
    scheme, hostname, port = origin
    if not _is_loopback_literal_host(hostname):
        return False
    if _truthy_env(ORCHESTRATOR_VIA_FLAG):
        return True
    sidecar = os.environ.get(ORCHESTRATOR_BASE_ENV, "").strip()
    if not sidecar:
        return False
    sidecar_origin = _http_origin(urllib.parse.urlparse(sidecar))
    if sidecar_origin is None:
        return False
    sidecar_scheme, sidecar_host, sidecar_port = sidecar_origin
    if not _is_loopback_literal_host(sidecar_host):
        return False
    return (scheme, hostname, port) == (sidecar_scheme, sidecar_host, sidecar_port)


def reject_private_llm_url(api_url: str) -> None:
    """Reject non-sidecar localhost, private, and non-http(s) LLM targets."""
    if not (api_url.lower().startswith("http://") or api_url.lower().startswith("https://")):
        raise ValueError(
            "URL scheme must be http or https; NOEMA_LLM_API_URL must start "
            "with http:// or https:// to prevent SSRF vulnerabilities"
        )
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(
            "URL scheme must be http or https; NOEMA_LLM_API_URL must start "
            "with http:// or https://"
        )
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must have a valid hostname")
    if is_allowed_orchestrator_sidecar_url(api_url):
        return
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise ValueError("URL cannot target localhost")
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return
    for result in addrinfo:
        ip_str = result[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError("URL cannot target internal IP addresses")


def call_llm(
    repo: str,
    number: int,
    pr: dict[str, Any],
    diff: str,
    truncated: bool,
    review_context: str = "",
) -> dict[str, Any]:
    """Call the configured OpenAI-compatible LLM endpoint for a review verdict."""
    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()
    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()
    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "noema-default"
    if not api_url or not api_key:
        raise RuntimeError("Noema LLM review unavailable: NOEMA_LLM_API_URL or NOEMA_LLM_API_KEY is not configured.")
    reject_private_llm_url(api_url)

    prompt = {
        "role": "user",
        "content": "\n".join(
            [
                "You are Noema, an independent pull request reviewer for ContextualWisdomLab.",
                "Review the PR diff plus the additional changed-file, review-thread, and CodeGraph context for correctness, security, maintainability, and behavioral regressions.",
                "Return only JSON with this shape:",
                '{"decision":"approve|request_changes|comment","summary":"...","findings":[{"severity":"high|medium|low","file":"path","line":1,"message":"..."}]}',
                "Use request_changes only for blocking, concrete issues. Use approve when no blocking issue is found.",
                f"Repository: {repo}",
                f"PR: #{number}",
                f"Title: {pr.get('title') or ''}",
                f"Head SHA: {pr.get('headRefOid') or ''}",
                f"Diff truncated: {truncated}",
                "Additional context:",
                review_context or "No additional context was available.",
                "Diff:",
                diff,
            ]
        ),
    }
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Return strict JSON only. Do not include markdown."},
            prompt,
        ],
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirectHandler())
    with opener.open(request, timeout=120) as response:  # nosec B310
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    verdict = extract_json_object(content)
    decision = str(verdict.get("decision") or "").strip().lower()
    if decision not in {"approve", "request_changes", "comment"}:
        raise RuntimeError(f"Noema LLM returned unsupported decision: {decision!r}")
    return verdict


def format_findings(findings: Any) -> list[str]:
    """Format bounded LLM findings for a GitHub review body."""
    if not isinstance(findings, list):
        return []
    lines: list[str] = []
    for finding in findings[:20]:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "info")
        file_name = str(finding.get("file") or "unknown")
        line = finding.get("line")
        location = f"{file_name}:{line}" if isinstance(line, int) and line > 0 else file_name
        message = str(finding.get("message") or "").strip()
        if message:
            lines.append(f"- [{severity}] {location}: {message}")
    return lines


def submit_review(repo: str, number: int, pr: dict[str, Any], actor: str, verdict: dict[str, Any]) -> None:
    """Submit the Noema review verdict to the pull request."""
    head_sha = str(pr.get("headRefOid") or "")
    decision = str(verdict.get("decision") or "comment").lower()
    event = "APPROVE" if decision == "approve" else "REQUEST_CHANGES" if decision == "request_changes" else "COMMENT"
    source = os.environ.get("NOEMA_REVIEW_TOKEN_SOURCE") or "NOEMA_REVIEW_TOKEN"
    summary = str(verdict.get("summary") or "Noema completed an independent LLM review.").strip()
    findings = format_findings(verdict.get("findings"))
    body = "\n".join(
        [
            "## Noema LLM review",
            "",
            summary,
            "",
            "### Findings",
            *(findings or ["- No blocking findings."]),
            "",
            f"- Result: {event}",
            f"- Head SHA: `{head_sha}`",
            f"- Reviewer credential: `{source}`",
            f"- Actor: `{actor or 'unknown'}`",
            "",
            f"<!-- noema-review-gate head_sha={head_sha} decision={decision} -->",
        ]
    )
    payload = {
        "commit_id": head_sha,
        "event": event,
        "body": body,
    }
    run(
        ["gh", "api", "-X", "POST", f"repos/{repo}/pulls/{number}/reviews", "--input", "-"],
        stdin=json.dumps(payload),
    )
    print(f"Noema {event} review submitted for {repo}#{number} at {head_sha}.")


def inspect_and_review(repo: str, number: int) -> int:
    """Inspect PR state and submit Noema's LLM review when gates are clean."""
    pr = fetch_pr(repo, number)
    actor = current_actor()
    if actor in PRIMARY_REVIEW_AUTHORS:
        print(
            f"Current token actor {actor!r} is already a primary review actor; "
            "Noema review skipped so GitHub receives an independent reviewer."
        )
        return 0
    if pr.get("isDraft"):
        print("PR is draft; Noema review skipped.")
        return 0
    if existing_noema_review(pr, actor):
        print("Current head already has a Noema review; nothing to do.")
        return 0
    if not current_primary_approval(pr):
        print("Current head does not have a primary OpenCode approval; Noema review skipped.")
        return 0
    if has_current_changes_requested(pr):
        print("Current head has requested changes; Noema review skipped.")
        return 0
    if has_unresolved_threads(pr):
        print("PR has unresolved review threads; Noema review skipped.")
        return 0
    blockers = blocking_checks(pr)
    if blockers:
        print("Blocking checks remain; Noema review skipped:")
        for blocker in blockers:
            print(f"- {blocker}")
        return 0
    diff, truncated = fetch_diff(repo, number)
    review_context = build_review_context(repo, number, pr)
    verdict = call_llm(repo, number, pr, diff, truncated, review_context)
    submit_review(repo, number, pr, actor, verdict)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse Noema review gate command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the Noema review gate command."""
    args = parse_args(argv)
    if args.pr_number <= 0:
        raise SystemExit("--pr-number must be positive")
    return inspect_and_review(args.repo, args.pr_number)


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
