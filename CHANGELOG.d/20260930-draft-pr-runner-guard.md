## Changed

- Draft pull requests no longer take a control-runner slot for the OpenCode,
  Strix, CodeQL PR and merge-scheduler entry jobs. They previously ran only to
  conclude that a draft needs no verdict; marking the pull request ready runs
  them again on the same head. Noema is unchanged because it reads the live
  draft state.
