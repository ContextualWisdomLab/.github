# Exact non-ZDR canary (default disabled)

Direct user consent covers ONLY ContextualWisdomLab/traveling-agent PR4,
head bf85ddde01f871f0e713db54aae5a16883777d9f, added file
`.github/workflows/docker-ephemeral-canary.yml`, SHA256
5427ca0c17d818d49f9af91b5cd495ab4599c969b894cb2467b794d674a96d3d.

Consent includes disclosed gateway prompt/response storage without an established
finite deletion period and the external classifier/provider/fallback chain.
It is NOT ZDR, an upstream no-training claim, or organization-wide consent.
Never enable PERSONAL_REVIEW_ZDR_ATTESTED on this basis.

Trusted variable NOEMA_EXACT_CANARY_NON_ZDR defaults false. Its true mode requires
a separate NOEMA_EXACT_CANARY_API_KEY Secret: no fallback to or overwrite of the
unresolved central Secret. Dedicated issuance/install must have authorized issuer
custody receipts before activation. No dedicated Secret has been installed by
this patch. The existing App publisher and exact-head verification are unchanged.
The canary requires native GitHub App selection. If NOEMA_REVIEW_TOKEN would
preempt the App, or only OIDC is available, credential selection explicitly rejects
before model work; ambient GH_TOKEN is never borrowed. Normal mode retains its
existing credential precedence. Activation must resolve this prerequisite without
silently replacing any existing Secret.

Workflow changes require two distinct probes under the existing substantive
validator. The emitted schema and fixed approval instruction require two as well;
one-probe responses remain rejected rather than weakening that validator.

Admission authenticates current head, one added path and exact content digest.
The HTTP producer repeats these checks and serializes only the approved YAML,
fixed instructions/identities and fixed verdict schema; PR title, review threads,
base source and caller diff do not enter the outgoing canary payload. The local
verdict validator receives a reconstructed new-file diff for line validation.
All other targets in this mode fail closed. Normal mode keeps existing private
retention admission unchanged. This patch does not authorize deployment/merge.
