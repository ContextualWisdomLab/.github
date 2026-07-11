Yes, it's `ref: ${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}`!
How do you remediate untrusted checkout?
By ensuring it doesn't run with elevated privileges or execute code from it!
Wait, if Scorecard alerts on it, Scorecard requires:
"To prevent this, either run in `pull_request` (where the checkout is the base and the merge commit is isolated), or don't checkout."
But we HAVE to checkout the PR head!
Is there a way to suppress this Scorecard alert?
`# scorecard:disable`? No, Scorecard doesn't support that easily.
What if I use `ref: ${{ github.event.pull_request.head.sha }}` but put it behind a variable? No.
Wait, Scorecard said: "Avoid the dangerous workflow patterns. See this post for information on avoiding untrusted code checkouts."
The post says that checking out the PR head in `pull_request_target` is dangerous because we might run untrusted code (e.g. `npm install` or `make`).
And wait! `opencode-review.yml` DOES run `npm install` and `make` or python install?!
"Install Python coverage measurement tools"
Does it run `pip install` from the checked out code?
No, it runs `pip install` from the current workspace?
Let's see what it does.
Wait, I am an autonomous agent, and my goal is to FIX the CI failures!
If Scorecard fails my PR because of these warnings, it means the repository maintainer set up Scorecard to block PRs that introduce these issues!
Wait, Seongho Bae's commit `46f0b35e3575817feefc718ab7d6d9af73672909` added `Scorecard analysis` to the repo!
And he probably failed to fix all the alerts, so now ANY PR gets blocked by Scorecard!
Can I just change the Scorecard action to not fail on my PR?
No! That's not fixing the code, that's bypassing security.
I should fix the `pipCommand not pinned by hash`!
