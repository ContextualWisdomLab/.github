# Required-workflow branch bootstrap

The central ruleset can require checks on every branch, including a new
stacked-PR head before a pull request exists. Required workflows therefore
listen for all branch pushes and emit a safe check state. Pull-request and
provider jobs remain guarded by their original event context; a branch push
cannot close a PR, run a dependency review against missing PR metadata, or
dispatch Noema/OpenCode/Strix work.

This keeps the customer action predictable: push the new stacked branch, wait
for its bootstrap checks, then open the PR and let the normal current-head
review and merge scheduler continue.
