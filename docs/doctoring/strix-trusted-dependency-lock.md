# Strix privileged dependency-lock boundary

## Observed failure

Repository-dispatch run `32651685973` scanned pull request #1263 and reported a
high-severity supply-chain path in the protected `pull_request_target` Strix
workflow. The workflow copied `requirements-strix-ci-hashes.txt` from the pull
request head, installed the selected distributions, and later executed the
installed `strix` console script with provider credentials.

The hosted report overstated its proof as a demonstrated exploit: the dispatch
path did not take the same-repository `pull_request_target` copy step, and the
artifact contained no malicious package command or output. The source path was
nevertheless deterministic and security-relevant. Hashes selected by the same
untrusted pull request authenticate attacker-selected content; they do not make
that content trusted.

## Root cause and repair

The workflow treated a hash lock as trusted because every distribution was
pinned and hashed. That protects a reviewed lock from index tampering, but it
does not establish the provenance of a lock supplied by a pull request.
GitHub's privileged-trigger guidance requires pull-request content to remain
data and never become executed code. pip's secure-install guidance separately
requires hash checking and disallows source distributions.

The repair deletes PR-head lock materialization. The install step now:

1. reads only the lock from the trusted workflow checkout;
2. rejects a missing or symbolic-link lock;
3. compares the on-disk Git blob with `HEAD:requirements-strix-ci-hashes.txt`
   immediately before installation; and
4. pins LiteLLM to the first compatible release with a Python 3.13 manylinux
   wheel, then installs with `--require-hashes`, `--only-binary=:all:`, and
   `--no-deps`.

Pull-request copies of the workflow and scheduler remain bounded self-test or
scan inputs; they do not select installed dependencies or receive provider
credentials.

## Scanner, credential, and status boundary

Default-branch dispatch run `32656142905` then tested the repaired branch with
the direct OpenAI provider and reported eight possible trust-boundary failures.
The credential-inheritance claim did not match the pinned `strix-agent==1.5.3`
runtime: its default backend is Docker, target commands run through a sandbox
manifest, and that manifest contains only the proxy, host identity, and Python
runtime variables required by Strix. The hosted proof used a fake scanner that
executed target code directly on the runner, which the pinned scanner does not
do.

The workflow now executes the installed Strix session-construction path before
loading provider credentials. It fails if the backend is not Docker or if the
sandbox manifest adds any host environment key outside the reviewed allowlist.
This proves only the target-command environment boundary. It does not claim
network isolation or read-only source mounts.

GitHub creates a distinct `GITHUB_TOKEN` for each job. The `strix` job currently
retains `statuses: write` only because protected main's trusted required-workflow
smoke pins that live permission layout. The gate constructs the scanner child
environment from an allowlist that omits both `GITHUB_TOKEN` and
`GITHUB_STATUS_TOKEN`, so the scanner process cannot exercise the job token's
status authority. The separate follow-up job has no `statuses: write`
permission; after the scan exports evidence that repository-dispatch inputs
matched live pull-request number, base SHA, and head SHA, it publishes with an
exchanged app token.

## Report evidence boundary

The remaining hosted findings exposed real fail-open behavior in the shared
gate. The repair applies one rule to every scanner attempt and report format:

- a nonzero scanner exit is incomplete evidence even when all emitted findings
  are below the configured severity threshold;
- Markdown and JSON vulnerability reports enter the same severity and
  changed-path mapping gate;
- report roots and every descendant must be ordinary non-symlink paths before
  classification, copying, or publication;
- a finding in a changed file blocks regardless of its reported line range;
  and
- a report path outside a narrowed scan target is unmappable failure evidence,
  not an unchanged baseline exemption.

Absolute paths that identify a file actually materialized in the narrowed scan
target remain mappable. This preserves legitimate Strix output without allowing
an outside-target path to be normalized against the repository root.

## Verification

- A static regression rejects any PR-head materialization of the Strix lock and
  requires the trusted Git-blob comparison and binary-only install.
- The short required-workflow smoke test enforces the same boundary.
- The workflow contract verifies Docker-backed sandbox construction, isolated
  status permission, and live dispatch metadata evidence.
- Realistic regressions cover nonzero low-severity output, JSON findings,
  symlinked report trees, changed-file line drift, narrowed-target escapes, and
  absolute paths inside the active target.
- The complete Strix shell harness, Python suite, actionlint, Bash syntax, and
  source-tree coverage run on the final exact head.

## References

GitHub. (n.d.). *GITHUB_TOKEN*. GitHub Docs. Retrieved August 24, 2026, from
https://docs.github.com/en/actions/concepts/security/github_token

GitHub. (n.d.). *Secure use reference*. GitHub Docs. Retrieved August 24, 2026,
from
https://docs.github.com/en/actions/reference/security/secure-use

GitHub. (n.d.). *Securely using pull_request_target*. GitHub Docs. Retrieved
August 24, 2026, from
https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 24, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

Python Packaging Authority. (2026). *Secure installs (pip 26.2.1
documentation)*. https://pip.pypa.io/en/stable/topics/secure-installs/

Python Software Foundation. (n.d.). *subprocess—Subprocess management*. Python
3 documentation. Retrieved August 24, 2026, from
https://docs.python.org/3/library/subprocess.html

Strix. (2026, August 10). *Strix* (Version 1.5.3) [Computer software]. GitHub.
https://github.com/usestrix/strix/tree/v1.5.3
