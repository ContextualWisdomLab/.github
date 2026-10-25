# Noema paid auto cost authorization (source proposal)

The October 25 CI request authorizes paid inference without a monetary cap on
`https://litellm.poinnetworks.net`, model `auto`. It does not require zero cost.
`NOEMA_REVIEW_PAID_AUTO_AUTHORIZED` is a separate, default-false cost authorization
for the existing Noema route. It does not attest privacy, select another key,
change endpoint/model, or relax private/internal visibility admission. Existing
OpenCode/Strix callers omit the new argument and keep their behavior.

Private/internal requests still require the existing real retention evidence and
`PERSONAL_REVIEW_ZDR_ATTESTED`. Do not set that value merely because a key has no
expiry, unlimited budget, no configured logging integration, or successful HTTP
responses. The variable's legacy PERSONAL name does not identify the key's owner.

Operational adoption requires normal independent source review and protected
shipment, purpose-bound existing central Secret custody, then truthful supplier
retention evidence for the gateway and every eligible downstream/fallback of its
literal auto route. No settings or Secrets are changed by this proposal. If the
supplier retains content, obtain an explicit privacy-policy decision instead of
calling it ZDR or silently falling back to another provider.
