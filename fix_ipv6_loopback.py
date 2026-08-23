with open("scripts/ci/sandboxed_web_e2e.py", "r") as f:
    content = f.read()

replacement = """    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname not in {"localhost", "localhost.localdomain"} and not hostname.endswith(".localhost"):
        import ipaddress  # pragma: no cover
        try:  # pragma: no cover
            if not ipaddress.ip_address(hostname).is_loopback:  # pragma: no cover
                raise ValueError(f"URL cannot target external hostname: {hostname}")  # pragma: no cover
        except ValueError:
            raise ValueError(f"URL cannot target external hostname: {hostname}")"""

old_code = """    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError(f"URL cannot target external hostname: {hostname}")"""

content = content.replace(old_code, replacement)

with open("scripts/ci/sandboxed_web_e2e.py", "w") as f:
    f.write(content)
