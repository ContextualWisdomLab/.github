# CI log evidence redaction

## Incident and boundary

PR #1242 briefly classified every standalone 40- or 88-character base64-like
value as a credential. A 40-character lowercase hexadecimal Git commit identity
therefore became `[REDACTED]`, destroying the exact-head evidence that protected
review and merge gates need. Length alone cannot distinguish an opaque secret
from a commit SHA or other legitimate evidence.

The redactor now uses the smallest reliable boundary:

- provider-specific, documented prefixes such as Stripe `sk_test_` and
  `sk_live_` may be recognized in unstructured text;
- opaque AWS and Azure values are redacted only when a sensitive assignment or
  JSON key supplies context, including `AWS_SECRET_ACCESS_KEY` and
  `AZURE_STORAGE_KEY`;
- unlabeled fixed-length strings remain visible so exact commit and artifact
  identities stay auditable.

This follows OWASP's requirement to keep secrets out of logs while retaining
the security events and audit fidelity needed for investigation. It also uses
the vendors' documented key names or prefixes instead of an inferred value
shape.

## Verification contract

`tests/test_opencode_security_boundaries.py` uses synthetic values to prove all
four outcomes: Stripe secret prefixes are removed, labeled AWS and Azure values
are removed, and unlabeled 40- and 88-character evidence is preserved. No real
credential or provider account data is stored in the repository.

## References

Amazon Web Services. (n.d.). *Configuring environment variables for the AWS
CLI*. Retrieved August 23, 2026, from
https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html

Microsoft. (n.d.). *Authorize access to blob data with Azure CLI*. Retrieved
August 23, 2026, from
https://learn.microsoft.com/en-us/azure/storage/blobs/authorize-data-operations-cli

OWASP Foundation. (n.d.). *Logging cheat sheet*. Retrieved August 23, 2026,
from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

OWASP Foundation. (n.d.). *Secrets management cheat sheet*. Retrieved August
23, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html

Stripe. (n.d.). *API keys*. Retrieved August 23, 2026, from
https://docs.stripe.com/keys
