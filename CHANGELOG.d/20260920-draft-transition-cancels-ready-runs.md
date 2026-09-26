### Draft transitions retire Ready workflow runs

- The five heavy required workflows now subscribe to `converted_to_draft`.
  Their existing pull-request concurrency groups cancel queued or running
  Ready work, while the Draft job guards keep the replacement run runner-free.
