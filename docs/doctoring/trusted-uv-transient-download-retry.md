# Trusted uv transient download retry boundary

## Decision

The central coverage materializer downloads one checksum-pinned uv archive from one literal Astral HTTPS URL. It performs at most **three total attempts**, separated by deterministic delays of one and two seconds, only for this closed availability set:

- HTTP `408`, `425`, `429`, `500`, `502`, `503`, and `504`;
- temporary DNS resolution reported as `EAI_AGAIN`;
- `TimeoutError`; and
- connection aborted, refused, or reset, plus explicit host or network down, reset, unreachable, or timed-out operating-system errors.

The fixed `GET` is safe and idempotent, so a bounded retry does not mutate remote or repository state. Each attempt repeats the same literal URL and exact timeout. The retry loop does not follow redirects, enable proxies, change the release URL, use repository-controlled headers, or accept an unverified payload.

NIST SP 800-218 PW.4.1 requires third-party software to come from expected,
trusted sources with integrity verification (Souppaya et al., 2022). Retrying
HTTP 425 Too Early (Thomson et al., 2018) or 429/5xx (Fielding et al., 2022)
is therefore an availability control only. It cannot widen the origin, skip
SHA-256 verification, or treat TLS and permanent DNS failures as transient.

## Fail-closed exclusions

The following conditions are never retried:

- every HTTP response outside the exact closed set, including authorization, not-found, and unsupported-method failures;
- certificate verification or any other TLS failure;
- permanent DNS failure;
- a malformed or non-exception `URLError.reason`;
- local permission failures and every unclassified `OSError`;
- redirect attempts or a final origin or port outside the fixed Astral HTTPS origin;
- an oversized archive;
- SHA-256 mismatch;
- malformed archive members, incorrect executable size or type, unsupported runner architecture, or unexpected uv version; and
- offline export, exact-pin grammar, Git-tree, TOML, or workspace-boundary failures.

A response body belongs to one attempt only. Partial bytes read before a transient failure are discarded before the next attempt. Retry exhaustion reports only a bounded HTTP status, transport errno, or exception class and the attempt count. It never includes exception text, URLs, response bodies, headers, credentials, or URL-derived user information.

The base-commit reader resolves `git` with `shutil.which("git", path=os.defpath)` and accepts only an absolute result. The ambient process `PATH` cannot select the executable; missing or relative resolution fails before any repository command runs.

## Descriptor-pinned output boundary

The generated-lock output path is treated as an untrusted namespace rather than as a stable object. Every directory component is created or opened relative to an already-open parent descriptor with `O_DIRECTORY`, `O_NOFOLLOW`, and `O_CLOEXEC`. The materializer compares the path entry's device and inode to the pinned descriptor immediately after open and again before reporting success. Removing, replacing, or redirecting the output pathname therefore fails closed; subsequent writes never re-resolve that mutable pathname.

Generated requirements and manifests are opened relative to the pinned output directory. A new file requires `O_CREAT | O_EXCL | O_NOFOLLOW`; a rerun opens an existing entry with `O_NONBLOCK | O_NOFOLLOW` before validating the descriptor as a singly linked regular file. This prevents an attacker-controlled FIFO with no reader from blocking `open()` before type validation; a non-blocking `ENXIO` is normalized to the same fail-closed regular-file rejection. Symbolic links, hard links, directories, FIFOs, and other special files are rejected before truncation. Each write is bounded by forward-progress checks and synchronized with `fsync`. After synchronization, both the published path and the pinned file descriptor must still identify the same singly linked regular inode; a hard link introduced during the write window therefore fails closed before success. The directory is then synchronized and revalidated.

This contract intentionally uses the POSIX descriptor-relative interface represented by `openat()` and Python's `dir_fd` operations. It prevents the check-then-use gap reported against the earlier `Path.exists()`/`Path.is_symlink()` followed by `Path.mkdir()` sequence. The central GitHub runner is Linux; a platform that does not provide the required no-follow and non-blocking descriptor flags fails at import or execution rather than silently falling back to pathname-based writes.

## Incident evidence

Central OpenCode coverage run `31002427460` for `ContextualWisdomLab/newsdom-api#524` reached the exact trusted-uv materialization stage and failed with `trusted uv archive download failed: HTTPError`. The source PR changed only `AGENTS.md`; all repository-local checks were successful. A later workflow in the same operating window downloaded the pinned uv release successfully, supporting a bounded transient-retry response rather than weakening the immutable bootstrap or bypassing coverage.

The same failure class later blocked exact-head OpenCode coverage for `ContextualWisdomLab/pg-llm-batch#53` in central workflow run `31022108085`. Repository-local CI, security, and SAST checks passed on that exact product head, while trusted uv archive materialization failed before PR-controlled tests ran.

Exact-head Strix run `31076540331` for organization control-plane PR `ContextualWisdomLab/.github#790` identified a medium-severity time-of-check/time-of-use race between output-directory symlink inspection and directory creation. The finding was valid rather than stale or infrastructure-only. Test-first commit `a1dcc679c1767f7e806793d7c0225a1342a9a875` captured intermediate symlink, pathname removal and replacement, generated-file symlink and hard-link, post-open swap, zero-progress write, and root-output regressions before descriptor-pinned production remediation.

A later exact-head independent review found a second valid race: a concurrent writer could add a hard link after the initial `st_nlink == 1` check while the descriptor remained bound to the same inode. RED commit `dc78b919e36011fa0f56e3ce9e334d3b1cb2261e` proved the existing implementation accepted that condition. The production fix revalidates regular-file type, device/inode identity, and single-link state after `fsync`, so the same race now fails closed.

A further independent review identified a bounded-denial-of-service gap in the existing-file path: `O_NOFOLLOW | O_WRONLY` could block forever when an attacker pre-created `requirements-000.txt` as a FIFO with no reader, before the subsequent `fstat()` regular-file check. RED commit `83f5a051785c0b21df92bbf1d1e0a7b7912dff55` added a deterministic regression that refuses to call the real blocking open unless `O_NONBLOCK` is present. Production commit `cf5c29e5179cab4f982c0078aaa02bd1cd321a38` adds the non-blocking flag and converts `ENXIO` into the existing fail-closed special-file rejection without weakening symlink, inode, link-count, or unexpected-error handling.

## Verification contract

Permanent tests require:

- every HTTP status in the exact closed set receives one bounded retry;
- representative permanent HTTP responses fail after one attempt and no sleep;
- temporary DNS, timeout, and connection-reset failures retry;
- certificate verification, permanent DNS, malformed transport reasons, and unclassified local errors fail after one attempt and no sleep;
- persistent transient failures stop after exactly three attempts and delays of one and two seconds;
- every attempt reuses the literal trusted URL and exact timeout;
- partial bytes from a failed response are absent from the next attempt;
- every output path component is opened without following symlinks and remains bound to the pinned descriptor;
- output-path removal or inode replacement fails closed after descriptor-relative writes;
- generated-file symlinks and multiply linked files are rejected before mutation;
- an existing FIFO without a reader is opened non-blocking and rejected without stalling the materializer;
- a hard link introduced after the initial file check but before final validation fails closed after the synchronized write;
- a singly linked regular generated file can be safely refreshed on a rerun;
- a post-open generated-file path swap and a zero-progress descriptor write fail closed; and
- the no-proxy opener, redirect rejection, final-origin validation, repeated bounded reads, maximum size, checksum, archive member, executable version, Python compatibility, offline export, full SHA-256 grammar, 100% statement and branch coverage, and production docstrings remain unchanged.

A permanent documentation contract rejects broader legacy wording such as all `URLError` or `OSError` failures and generic `5xx` retries.

## MSA and operational boundary

This retry and output hardening belong to the organization-owned coverage control plane because every leaf repository consumes the same trusted bootstrap. Leaf repositories such as pg-llm-batch, NewsDOM, and naruon must not duplicate a downloader, pathname race workaround, or weakened review gate. If all three attempts fail or any output binding changes, the current-head review remains fail-closed and publishes bounded evidence; no approval or merge is synthesized.

## Rollback

Rollback of the transport slice removes the retry constants and loop while retaining every immutable-source, no-proxy, no-redirect, bounded-read, checksum, archive, executable-version, and offline-export control. Operators may also set the delay tuple to empty in a reviewed change to restore one attempt. Increasing attempts, delays, or the closed classifier requires a separate availability, security, and runner-budget review.

The output-binding remediation must not be rolled back to pathname prechecks or blocking opens of untrusted existing entries. A safe rollback may stop materialization entirely or replace the implementation with an independently reviewed descriptor-relative or private-directory publication design that preserves no-follow opening, non-blocking rejection of special files, inode validation, regular-file validation, single-link validation before and after writes, and fail-closed behavior.

## References

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes* (RFC 6585). RFC Editor. https://doi.org/10.17487/RFC6585

Python Software Foundation. (2026). *os—Miscellaneous operating system interfaces*. Python 3.14 documentation. https://docs.python.org/3.14/library/os.html

Python Software Foundation. (2026). *urllib.error—Exception classes raised by urllib.request*. Python 3.14 documentation. https://docs.python.org/3.14/library/urllib.error.html

The Open Group. (2024). *open, openat—Open file relative to directory file descriptor*. In *The Open Group Base Specifications Issue 8, IEEE Std 1003.1-2024*. https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html

Thomson, M., Nottingham, M., & Tarreau, W. (2018). *Using early data in HTTP* (RFC 8470). RFC Editor. https://doi.org/10.17487/RFC8470
