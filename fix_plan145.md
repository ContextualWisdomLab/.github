In `strix.yml`, line 100 is top-level `statuses: write`. I will change it to `read`.
But wait, `strix.yml` has TWO jobs: `strix` and `publish-manual-pr-evidence-status`!
Does `strix` job need `statuses: write`?
Let's see if the `strix` job has job-level permissions!
