# Cloudflare Pages reusable-workflow secret and input contract

## Decision

The reusable Pages deployment declares and references exactly two required
secret names for compliant callers: `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID`. Approved CWL callers MUST map them explicitly and
MUST NOT use `secrets: inherit`:

```yaml
jobs:
  deploy:
    uses: ContextualWisdomLab/.github/.github/workflows/deploy-pages.yml@main
    with:
      project_name: example-marketing
      build_dir: ./public
    secrets:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

This is an explicit named interface and caller policy, not a GitHub runtime
allowlist. GitHub allows a same-organization or same-enterprise caller to use
`secrets: inherit`; secrets inherited that way can be referenced by the called
workflow even when they are not declared under `on.workflow_call.secrets`.
The declaration documents and validates explicit named mappings but cannot
disable GitHub's inheritance keyword. The called workflow itself references
only the two Cloudflare names above.

The workflow keeps `contents: read`, checks out the caller repository, and uses
the token only for Pages deployment and optional domain attachment. For an
approved explicit-mapping caller, GitHub rejects an invocation that omits either
required name before the job starts; the runtime guard remains a value-free
defense-in-depth check.

## Untrusted deployment inputs

Reusable-workflow string inputs are caller-controlled data. They are not
command, filesystem, Cloudflare-resource, or URL authority merely because the
caller is allowed to invoke the workflow. The workflow therefore validates the
three deployment inputs before any of them reaches Wrangler, a Cloudflare API
URL, or a shell-rendered summary.

`project_name` is bounded to a non-empty alphanumeric/hyphen identifier with an
alphanumeric first and last character. `build_dir` is bounded to a relative
POSIX-style path, may not contain option-like, traversal, whitespace, control,
or backslash syntax, must resolve to an existing directory, and must remain
inside the exact checked-out `GITHUB_WORKSPACE` after symlink resolution.
`custom_domain` is optional; when present it is bounded to DNS-style labels,
rejects path/query/fragment/port-like syntax, and is canonicalized to lowercase.
Invalid input fails with one generic value-free error rather than reflecting the
untrusted value.

Only the validator's sealed step outputs reach the Wrangler command, custom
domain API path, and job summary. The job display name is static so a raw
caller-supplied project name is not promoted into workflow presentation before
validation. The summary passes validated outputs through environment variables
rather than embedding raw GitHub expression text into the shell program.

Cloudflare's current Direct Upload documentation defines Pages deployment as
uploading one prebuilt asset directory with `wrangler pages deploy`, and its CI
guide uses the directory plus `--project-name=<PROJECT_NAME>`. This workflow
keeps exactly that product boundary while adding a stricter central validation
layer before argument construction. The validator is intentionally more
restrictive than accepting arbitrary strings: callers requiring a genuinely new
identifier/path shape must change the reviewed contract and its negative tests,
not bypass validation locally.

## Migration and acceptance

As of 2026-08-09, a current organization search found no product workflow that
calls this reusable workflow. Re-run that search before merge. Any consumer
found later must add the two explicit mappings in its thin caller under that
repository's writer lease. Treat any `secrets: inherit` caller as a leaf
migration defect, not a reason to broaden the central interface.

Acceptance requires workflow contract tests, syntax and supply-chain checks,
and realistic positive/negative input tests that execute the production
validator itself. At minimum the tests cover a normal project/build/domain,
argument-like project names, absolute/traversing/build-option paths, malformed
hostnames, and a symlink escaping the checkout. A protected-main caller canary
must prove that validated inputs reach Wrangler with both required secret
mappings. A missing-mapping negative control must stop before deployment and
must not print a credential.

## Failure and rollback

If a consumer cannot migrate immediately, pin it to the last reviewed workflow
revision while its caller is repaired. Do not broaden the new interface,
reintroduce blanket inheritance, or interpolate raw inputs as a compatibility
shortcut. Roll back the central contract only for a confirmed GitHub reusable-
workflow or Cloudflare platform defect, and preserve the explicit two-name
secret interface plus fail-closed input validation in the replacement
transport.

If validation rejects a previously accepted caller, first determine whether the
caller relied on a genuinely supported Cloudflare identifier/path shape or on
ambiguous input that should never have crossed the command/URL boundary. Extend
the validator only with a focused RED/GREEN contract and keep symlink escape,
traversal, option injection, and value-free diagnostics intact.

## APA 7th references

Cloudflare. (2026a). *Direct Upload*. Cloudflare Pages documentation.
https://developers.cloudflare.com/pages/get-started/direct-upload/

Cloudflare. (2026b). *Use Direct Upload with continuous integration*. Cloudflare
Pages documentation.
https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/

GitHub. (2026). *Reuse workflows*. GitHub Docs.
https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
