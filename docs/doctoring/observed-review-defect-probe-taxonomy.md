# Observed review defect probe taxonomy

OpenCode review publication uses a deterministic semantic taxonomy to turn demonstrated review misses and false positives into executable regressions. The closed classes are `mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, and `state_machine_race`.

A label alone is never proof. Each class has exactly three named semantic witness fields in `scripts/ci/review_probe_taxonomy.py`; every witness must be concrete, distinct, and quoted verbatim into the independently source-receipted probe evidence. Material reviews require distinct probe classes. This prevents two differently worded generic probes or repeated coordinates from satisfying adversarial diversity.

The durable observable-case corpus is `tests/fixtures/review_observed_defect_cases.json`. It deliberately contains both confirmed defects and false-positive corrections so reviewer quality is evaluated on finding real defects without inventing defects when an omitted entrypoint, dependency, or authority boundary explains the code. The corpus records observable ContextualWisdomLab cases rather than proprietary reviewer wording and makes no benchmark-superiority claim.

Production admission remains evidence-first: the model chooses hypotheses and findings, while deterministic validators only check that the submitted evidence is current-head, changed-line-bound, structurally complete, and semantically tied to the declared failure class. A validator does not manufacture a finding, infer a passing result, or substitute missing runtime evidence.
