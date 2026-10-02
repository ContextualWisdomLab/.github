### Review performance evidence distinguishes call overhead from scan complexity

- `.github#2562` no longer describes `str.rfind()` as eliminating linear input
  scanning or claims an unbound performance multiplier without a reproducible
  workload. The source comment, learning record, PR evidence, and gap baseline
  now name only the supported boundary: fewer Python-loop calls and no list of
  every match position. The learning date is corrected to 2026-10-02.
