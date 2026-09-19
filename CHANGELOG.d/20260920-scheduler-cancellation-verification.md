### Scheduler cleanup proves cancellation before completion

The required-review merge scheduler now revalidates the live pull request immediately before each superseded-run mutation and treats an accepted force-cancel request as incomplete until GitHub reports the run as `completed/cancelled`. Bounded executable regressions cover a concurrent head advance, a cancellation that never terminates, and a successful asynchronous cancellation.
