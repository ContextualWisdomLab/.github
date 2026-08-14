# Python requirement include materialization

## Decision

Trusted base Python requirement files may use pip's `-r` / `--requirement` include form only when the target is a bounded relative candidate lock path. The materializer flattens selected source locks into deterministic `requirements-NNN.txt` names for the Docker build context, so it must rewrite each accepted include to the generated name of the exact selected base-commit target. A missing target is a hard materialization failure rather than a deferred installer error.

Direct `.txt` children of a directory named `requirements` are eligible lock candidates when their content independently passes the hash-pin syntax gate. This keeps an accepted path such as `requirements/ci.txt` discoverable when a parent lock includes it.

## Verification

The regression fixture creates a parent `service/requirements.txt` that includes `service/requirements/ci.txt`, materializes both from an exact git base SHA, proves the parent references the generated child file, and asks pip to resolve the generated parent with `--dry-run --no-index --require-hashes`. Separate fail-closed tests cover unresolved include targets and non-UTF-8 content that cannot be rewritten faithfully. The dedicated materializer quality workflow includes this fixture in its 100% statement/branch coverage gate and compilation contract.

## Security boundary

Only already-validated two-token relative includes are rewritten. Absolute paths, traversal components, URLs, option-like targets, Windows separators, fragments, queries, and non-lock targets remain rejected before materialization. Rewriting uses the source lock's repository-relative parent directory and a deterministic source-to-generated-name map built from the exact validated base commit; pull-request filesystem state does not choose the target.

## Reference

Python Packaging Authority. (n.d.). *Requirements file format*. pip documentation. Retrieved August 15, 2026, from https://pip.pypa.io/en/stable/reference/requirements-file-format/
