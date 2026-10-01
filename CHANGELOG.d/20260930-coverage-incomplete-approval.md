### Incomplete Rust coverage cannot supply formal approval evidence

- A Rust coverage timeout now reports `NOT MEASURED`, never `PASS` or a
  claim that the timed-out suite passed. The advisory coverage job may finish
  successfully, but formal approval requires one unambiguous `PASS` decision
  from that same dispatch. Missing, unknown, malformed, and contradictory
  decisions withhold approval without manufacturing a source finding. Existing
  exact-head review and required-check gates remain in force; unmeasured
  coverage does not satisfy or replace required verification.
