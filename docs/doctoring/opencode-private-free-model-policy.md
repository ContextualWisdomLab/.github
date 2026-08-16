# OpenCode private-repository free-model policy

**Status:** Implemented design decision  
**Decision date:** 2026-08-08  
**Scope:** `ContextualWisdomLab/.github` OpenCode review control plane

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

A private repository may use the anonymous `opencode-free/*` review pool only when
its trusted pull-request base commit contains the exact policy file below and the
reviewed head does not add, remove, rename, chmod, or modify that file.

```text
.github/opencode-private-free-models.json
```

```json
{
  "schema_version": 1,
  "allow_private_free_models": true,
  "repository_data_classification": "public_equivalent",
  "external_model_data_use_accepted": true
}
```

The declaration means all tracked repository content that OpenCode can read is
approved for processing under the external free-model terms as though it were
public. It does **not** mean the repository becomes public, and it is not a
claim that a scanner proved the absence of every secret or confidential fact.

The pull request that introduces or changes the policy remains ineligible. The
policy takes effect only after that change has passed normal review and reached
the base branch, on a subsequent pull request. Protect this file with normal
branch protection and, where available, `CODEOWNERS` review.

## Why an explicit policy is required

Repository visibility and data sensitivity are different attributes. A private
repository may contain only non-sensitive open-source work, while another may
contain customer data, personal data, unreleased intellectual property, access
credentials, or confidential architecture. The absence of configured GitHub
Actions secrets does not classify the source tree.

GitHub secret scanning is an important independent control, but it detects
supported patterns rather than proving that no confidential information exists.
For organization-owned private and internal repositories, secret scanning
requires GitHub Secret Protection on an eligible plan. Therefore, model egress
is enabled by an auditable data-owner declaration, not by a heuristic scan or by
repository visibility alone.

NIST SP 800-53 Rev. 5 AC-3 requires access enforcement against an explicit
policy, and SC-8 requires confidentiality of information in transit (Joint Task
Force, 2020). A private GitHub repository is therefore not an implicit
authorization to send source to an external free-model endpoint. The trusted
base-branch declaration is the access policy; a head that adds or edits that
file cannot authorize its own egress.

## Provider-data and catalog boundary

OpenCode documents free models as limited offerings used to collect feedback or
improve models. Its privacy documentation warns that some free endpoints may
retain or use collected data and that personal or confidential data must not be
submitted. Accordingly, the policy is restricted to `public_equivalent`
repositories and requires explicit acceptance of external-model data use.

The governed anonymous pool is synchronized to the zero-cost OpenCode Zen catalog
published in the primary Zen documentation. At the current decision revision it
contains exactly these seven aliases:

1. `opencode-free/nemotron-3-ultra-free`
2. `opencode-free/deepseek-v4-flash-free`
3. `opencode-free/north-mini-code-free`
4. `opencode-free/laguna-s-2.1-free`
5. `opencode-free/ling-3.0-flash-free`
6. `opencode-free/big-pickle`
7. `opencode-free/mimo-v2.5-free`

Aliases previously carried as `hy3-free`, `minimax-m3-free`, `glm-5-free`,
`kimi-k2.5-free`, and `qwen3.6-plus-free` are not in the current documented
zero-cost catalog and are therefore removed before model selection. The wrapper
never infers that an arbitrary `opencode-free/*` prefix is actually free. A
catalog change requires an independently reviewable source update.

Candidate availability is still runtime-dependent. A provider rejection or
retirement remains ordinary bounded fallback evidence; it does not weaken review
or merge gates.

## Repository-visibility boundary

Preconfigured anonymous candidates are not themselves authorization. The wrapper
first needs positive visibility evidence:

- the live model-pool step MUST export
  `OPENCODE_REPOSITORY_IS_PRIVATE` from
  `needs.validate-pr-metadata.outputs.is_private` next to `PR_BASE_SHA`;
- a trusted caller may provide `OPENCODE_REPOSITORY_IS_PRIVATE=false`; or
- when that trusted signal is absent, the wrapper may prove only the **public**
  case by performing a credential-free `git ls-remote` against a strictly
  validated `https://github.com/ContextualWisdomLab/<repository>[.git]` origin.
  A timeout or transport failure on a public ContextualWisdomLab origin is not
  the production authorization path.

`true`, malformed visibility input, private/auth-required Git access, timeout,
transport failure, missing remote metadata, or any other indeterminate outcome is
fail-closed. The wrapper removes every preconfigured anonymous candidate and the
unchanged trusted-base policy becomes the sole re-enable path. The public probe
runs with GitHub, Actions, model-provider, and OIDC credentials removed and with
Git credential helpers disabled.

This preserves public-repository behavior without treating an untrusted candidate
list as visibility evidence and prevents a private caller from bypassing policy
by pre-populating `OPENCODE_MODEL_CANDIDATES`.

## Credential boundary

Each OpenCode subprocess receives only the credential for its selected provider.
In particular, an anonymous `opencode-free/*` process receives none of these
values:

- GitHub tokens
- GitHub Actions OIDC request credentials
- GitHub Actions runtime, cache, or results credentials
- OpenCode application tokens
- NVIDIA NIM keys
- OpenCode Zen keys
- OpenAI keys
- OpenRouter keys
- GitHub Models tokens

Session export runs without any provider credential. Unknown future provider
prefixes also default to zero provider credentials until they are explicitly
classified. The guard recognizes OpenCode's long and short model selectors
(`--model`, `--model=`, `-m`, and `-m=`), rejects duplicate or missing model
selectors, and stops option parsing at `--` so argument text cannot accidentally
change credential selection.

The model remains read-only under the existing OpenCode review agent contract.
Credential isolation does not make confidential source safe to send to an
external model; the repository-level data classification remains the primary
eligibility control.

## Fail-closed validation

The policy checker:

- accepts only full 40-character base and head commit SHAs;
- reads the policy directly from the immutable base Git tree;
- rejects a policy changed by the current head;
- requires the `git ls-tree -z` response to be exactly one NUL-terminated record,
  rejecting truncated or extra records rather than reconstructing delimiters;
- accepts only one regular, non-executable `100644` blob at the fixed path;
- limits the blob to 4,096 bytes;
- requires strict UTF-8 and JSON without duplicate keys;
- rejects missing or unknown fields and requires the exact canonical values;
- ignores system and user Git configuration and disables hooks and filesystem
  monitors during evaluation;
- removes preconfigured anonymous candidates on private or unverified calls before
  policy evaluation; and
- leaves the existing keyed/private fallback pool unchanged on every denial or
  local evaluation error.

The model-pool boundary also validates integer runtime, retry, cycle, and export
controls before shell arithmetic or `timeout` consumption. Malformed values fall
back to reviewed defaults rather than reaching Bash arithmetic or busy-looping a
runner.

## Operating procedure

1. Confirm the repository contains no credentials, personal data, customer data,
   confidential documents, restricted source, or other data prohibited by the
   free-model terms.
2. Resolve active secret-scanning alerts and enable Secret Protection, push
   protection, generic patterns, and organization-specific custom patterns where
   available.
3. Add the exact policy file in a separately reviewed pull request.
4. Merge that policy through normal branch protection. Its own pull request will
   not use the private free pool.
5. On a later pull request, verify the OpenCode log records that the unchanged
   trusted base policy enabled the anonymous candidates and verify the selected
   child environment contains no GitHub, Actions, OIDC, or provider credentials.
6. Run a private negative control without the policy and verify anonymous
   candidates remain disabled while configured keyed fallbacks remain available.
7. To disable the feature, remove or change the policy through a normal pull
   request. The change takes effect after merge; the policy-changing pull request
   itself remains fail-closed.

## Rejected alternatives

### Infer eligibility from missing Actions secrets

Rejected because repository source, history, fixtures, issues, and generated
review evidence may be confidential even when no Actions secret is configured.

### Let the current pull-request head add an opt-in marker

Rejected because untrusted code could authorize its own external disclosure.
The marker must already exist on the base and remain unchanged in the head.

### Trust a preconfigured `opencode-free/*` candidate as proof of eligibility

Rejected because candidate text is not a data-classification or visibility
signal. Private or unverified callers must pass the immutable-base policy gate.

### Send all provider keys and rely on agent instructions

Rejected because a model process does not need unrelated credentials. Provider
selection is enforced in the process environment rather than by prompt text.

### Treat secret scanning as a proof of public-equivalent data

Rejected because secret scanning is a defense-in-depth detector, not a complete
information-classification system.

## Verification evidence

The implementation includes tests for valid base policy activation, missing and
self-added policies, head mutations, unknown and weaker declarations, duplicate
JSON keys, symlinks, oversized blobs, malformed UTF-8 and JSON, Git failures,
truncated and extra `ls-tree -z` records, provider-specific credential retention,
anonymous free credential removal, short and long model selectors, option
termination, export isolation, unknown-provider fail-safe behavior, private
preconfigured-free bypass rejection, catalog filtering, visibility fail-closed
behavior, runtime integer controls, and wrapper ordering.

Operational acceptance remains separate from code-level tests. Issue #833 tracks
the required protected-base private canary, negative control, credential-absence
evidence, schema/evidence validation, independent review/protection gates, and
rollback rehearsal.

## References

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST SP 800-53 Rev. 5). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-53r5

GitHub. (n.d.-a). *Enabling secret scanning for your repository*. GitHub Docs.
Retrieved August 8, 2026, from
https://docs.github.com/en/code-security/how-tos/secure-your-secrets/detect-secret-leaks/enable-secret-scanning

GitHub. (n.d.-b). *Secrets*. GitHub Docs. Retrieved August 8, 2026, from
https://docs.github.com/en/actions/concepts/security/secrets

OpenCode. (n.d.). *Zen*. Retrieved August 9, 2026, from
https://opencode.ai/docs/zen
