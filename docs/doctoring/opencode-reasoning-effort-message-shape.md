# OpenCode reasoning-effort validation message shape

## Decision

`validate_candidate` still requires reasoning-capable models to declare
`reasoning=true`, `options.reasoningEffort=high`, and
`variants.high.reasoningEffort=high`. The repair only extracts the shared
error prefix and suffix so those three checks cannot drift apart.

Fowler (2018) records Extract Variable as the smallest way to keep repeated
literal fragments identical. ISO/IEC 25010:2023 treats analysability and
modifiability as maintainability characteristics (International Organization
for Standardization, 2023). The extracted fragments do not change the
fail-closed contract: an undefined GitHub Models or known-reasoning
candidate still errors, and a non-reasoning model without `reasoning=true`
still passes.

## References

Fowler, M. (2018). *Refactoring: Improving the design of existing code*
(2nd ed.). Addison-Wesley.

International Organization for Standardization. (2023). *Systems and
software engineering—Systems and software Quality Requirements and
Evaluation (SQuaRE)—Product quality model* (ISO/IEC 25010:2023).
https://www.iso.org/standard/78176.html
