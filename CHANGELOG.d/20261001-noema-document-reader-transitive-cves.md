### Noema document reader transitive security updates

- Updated the locked `fast-uri` dependency from 3.1.7 to 3.1.8 and
  `ip-address` from 10.7.0 to 10.7.1. These are the first releases outside
  the affected ranges for GHSA-hrr3-gc8f-f4qj, GHSA-j6r3-76f7-8jcv, and
  GHSA-h3mg-xc3c-68pw. The direct dependency ranges are unchanged.
- Added a deterministic regression contract that rejects reintroduction of
  vulnerable hoisted or nested copies of either transitive package. The
  contract uses semantic version ordering so prereleases of a fixed version do
  not satisfy the corresponding final-release minimum.
