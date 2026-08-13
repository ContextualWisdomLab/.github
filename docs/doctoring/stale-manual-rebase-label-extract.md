# Stale manual-rebase label extract

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

`perform_rebase` still rebases a same-repository behind or dirty pull
request, force-pushes with lease on success, and labels plus comments on
conflict. A labeled-and-dirty candidate remains skipped upstream. The
extracted `clear_stale_manual_rebase_label` helper only removes the
`manual-rebase` label when that skip no longer applies, so a later base
change cannot leave the PR permanently blocked.

Fowler (2018) records Extract Method as the smallest way to keep a
side-effecting policy visible and independently testable. ISO/IEC
25010:2023 treats analysability and modifiability as maintainability
characteristics (International Organization for Standardization, 2023).
The helper returns audit notes and does not change git mutation,
credential, or comment behavior.

## References

Fowler, M. (2018). *Refactoring: Improving the design of existing code*
(2nd ed.). Addison-Wesley.

International Organization for Standardization. (2023). *Systems and
software engineering—Systems and software Quality Requirements and
Evaluation (SQuaRE)—Product quality model* (ISO/IEC 25010:2023).
https://www.iso.org/standard/78176.html
