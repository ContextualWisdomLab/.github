# Model workflow native concurrency runtime proof

This probe records two successive pull-request heads created after central
workflow-level concurrency shipped in `.github` PR #1854. The first head
establishes Strix, OpenCode, and Noema runs under the new group contract; the
second head records whether GitHub natively cancels those superseded runs.

The expected group shape is `<workflow>-ContextualWisdomLab/.github-<PR>`.
Different workflows, repositories, and pull requests remain independent.
