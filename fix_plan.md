The CI run failed on `opencode-review`.
Error message: `No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head. The dispatch workflow will rerun this failed job after publishing an authenticated exact-head verdict.`
From the instructions:
"CI workflow checks such as opencode-review, noema-review, strix, and CodeQL compatibility analysis rely on asynchronous polling and may fail transiently due to rate limits (e.g., HTTP 429), unavailable providers/backends, or missing terminal verdicts from external bots (e.g., opencode-agent). These represent environmental/timing states rather than code failures, and do not require codebase changes to resolve."
"When resolving asynchronous CI polling failures (like CodeQL compatibility analysis, noema-review, opencode-review, or strix) that require no codebase changes, you must still include the complete test suite execution in your plan. Do not use execution plan steps to write out conversational explanations or quote memory rules; strictly use concrete execution steps to run the tests followed by task completion."

So this means the failure is a transient environmental error that does NOT require codebase changes. I just need to:
1. Run the full test suite again.
2. Complete pre-commit.
3. Submit the fix.

Let's do this!
