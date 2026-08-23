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

## Verification

- A static regression rejects any PR-head materialization of the Strix lock and
  requires the trusted Git-blob comparison and binary-only install.
- The short required-workflow smoke test enforces the same boundary.
- The complete Strix shell harness, Python suite, actionlint, Bash syntax, and
  source-tree coverage run on the final exact head.

## References

GitHub. (2026). *Secure use reference*. GitHub Docs.
https://docs.github.com/en/actions/reference/security/secure-use

Python Packaging Authority. (2026). *Secure installs (pip 26.2.1
documentation)*. https://pip.pypa.io/en/stable/topics/secure-installs/
