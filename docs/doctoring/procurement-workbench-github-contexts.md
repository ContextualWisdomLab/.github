# GitHub context and actionlint evidence

Collected: 2026-10-09 KST.

Official GitHub Actions contexts documentation fetched from:
`https://docs.github.com/en/actions/reference/workflows-and-actions/contexts`

The cached copy is local scratch evidence:
`/Users/seonghobae/.hermes/cache/scratch/github-contexts-doc.html`

Observed official entries:

- `job.workflow_ref`: documented as the full ref of the workflow file that defines the current job. For reusable workflows this refers to the reusable workflow file.
- `job.workflow_sha`: documented as the commit SHA of the workflow file that defines the current job.
- `job.workflow_repository`: documented as the owner/repo of the repository containing the workflow file that defines the current job.
- `job.workflow_file_path`: documented as the file path of the workflow file that defines the current job.

Installed validator:

- `actionlint -version`: `1.7.12`, built with Go 1.26.1 for darwin/arm64.
- It rejects these documented `job.workflow_*` context fields as undefined.

Decision and current state (2026-10-10 KST):

- Historical direct `job.workflow_*` expressions failed actionlint1.7.12; original diagnostics remain in earlier reviews. No ignore or suppression was added.
- Current candidate uses the supported `toJSON(job)` expression. Inline isolated Python reads the same documented defining-workflow fields and rejects missing/nonobject/invalid SHA/wrong repository/file/mutable ref metadata. It never substitutes caller `github.workflow_sha`.
- Actual positive and malformed-context tests validate the parser. Current actionlint1.7.12 returns exit0 on this workflow. This proves syntax/schema acceptance of serialization, not GitHub runtime availability of those fields.
- Actual Actions canary must prove serialized context includes the defining repository/SHA/ref/file and immutable caller pin. Missing fields fail before checkout; activation remains HOLD until runtime evidence exists.
