# CodeQL SARIF publication boundary

The central CodeQL dispatch handler publishes a terminal commit status only after the same matrix shard has successfully preserved its SARIF artifact. A successful finding gate without durable evidence is not a successful scan contract: upload failure, a skipped upload, cancellation, or a missing outcome fails closed before any status credential is used and therefore before the exact required job can be woken.

`actions/upload-artifact` owns the evidence boundary. The upload step has a stable step identifier and rejects an empty artifact input. The status-publication step consumes that step's outcome and accepts only `success`; it does not infer preservation from a generated local file or from the SARIF gate result. The gate result continues to determine whether preserved evidence represents a passing or failing security verdict.

Executable regression coverage runs the real publication shell against a fixture-backed GitHub API. The success control permits one exact-head status post. Upload outcomes `failure`, `skipped`, `cancelled`, and empty each exit before a post, preventing a false terminal success and the downstream exact-job rerun.

This source repair does not change repository-dispatch actor authorization or cross-repository credential authority. Those remain separate configuration and GitHub App permission boundaries tracked in ContextualWisdomLab/.github issue #1929.
