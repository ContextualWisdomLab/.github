# Fixed helper source for release gates

The three trusted checkouts use literal repository `ContextualWisdomLab/.github`
and reviewed helper revision `00c6551183cca101cfc97c43656a17cc2491c1b4`.
This is an independent helper revision, not an assertion that helper and called
workflow revisions are equal. A future workflow change does not silently update
these helper bytes. Updating the pin and content identities requires review.

All three checkouts materialize `scripts/ci/` and
`requirements-strix-ci-hashes.txt`, preserving helper siblings. Before executing
helpers they verify checkout HEAD, canonical origin URL, the scripts tree
`bf26d3eefdb71fe79b855d941ffb46eb432b2f76`, lock blob
`9e705850b5ce53c7fe836bc3df3a18771151e3f6`, tracked-file cleanliness and required
entrypoints. Missing, foreign or mismatched source rejects. The step reports
helper repository/SHA separately from caller workflow SHA. The latter is only
provenance context, never a checkout selector or authorization input.

GitHub's [current context reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context)
documents called-job workflow identity fields, but actionlint 1.7.12 and the
inspected upstream main strict schema do not yet support them. This alternative
uses neither those expressions nor an ignored diagnostic or permissive schema.
It changes the contract from called-self checkout to an explicitly adopted
fixed helper snapshot. The earlier called-self candidate remains separate.

Local synthetic guards exercise valid identity, another caller SHA, missing
git source, foreign origin, wrong HEAD/tree, dirty tracked files and a missing
entrypoint. They do not perform checkout or network access. Hosted checkout and
attestation behavior remain unexecuted.

`SOURCE_SHA == GITHUB_SHA`, full licence/Strix authorization, twelve-platform
closure and complete resource intake budgets remain unresolved independently.
No condition is relaxed by this source-selection fix. The pinned snapshot
retains its existing licence/tool-dependency limitations; exact-byte provenance
does not imply policy acceptance.
