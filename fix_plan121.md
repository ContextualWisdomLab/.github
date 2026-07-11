Wait, if Scorecard alerts me about `untrusted code checkout`, `permission set to write`, and `pipCommand not pinned by hash`...
Scorecard annotations in GitHub Actions don't *fail* the workflow by themselves unless they are configured to fail!
Let's see if Scorecard ACTUALLY failed the CI run!
In the prompt:
`## Failed Check Run 1: Scorecard`
`Conclusion: failure`
And the annotations are listed.
Is it the `Scorecard` check that fails my PR?
Yes! "Your task is to analyze the above information and fix the errors causing these CI failures."

Wait, how did Scorecard fail?
"Conclusion: failure"
"Title: 1 configuration not found"
"Warning: Code scanning may not have found all the alerts introduced by this pull request, because 1 configuration present on refs/heads/main was not found: supply-chain/branch-protection"
Wait! The `supply-chain/branch-protection` configuration is NOT FOUND!
Is that why it failed?!
If a configuration is not found, maybe I need to add it?
Where is the `scorecard-analysis.yml` workflow?
