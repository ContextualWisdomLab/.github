# Strix ModelBehaviorError classifier

Observed required-check flake: Strix exits 1 with `ModelBehaviorError` and
`Vulnerabilities 0` after the scanner model fails to complete a turn.

The outer `strix.yml` backend-unavailable signal now includes
`ModelBehaviorError`. Neutral skip still requires the absence of
`Vulnerabilities [1-9]` and of a `severity:` finding. A scan that reports
any numbered vulnerability stays fail-closed even when the model also
emits `ModelBehaviorError`.
