# Agent-mention sweep parallel discovery

## Incident and buyer impact

The organization mention sweep walked every repository serially. A bounded
`max_dispatches` return still waited for queued GitHub list calls. Mentions
from later repositories arrived after the dispatch budget was already spent.

## Decision

Keep repository order deterministic. Use a serial path for zero or one
repository. Bound parallel fetches to five workers. Share a cancellation
event checked between pages. On early close, cancel queued futures and shut
down without waiting. Isolate per-repository errors on the caller thread.

## References

Goetz, B., Peierls, T., Bloch, J., Bowbeer, J., Holmes, D., & Lea, D.
(2006). *Java concurrency in practice*. Addison-Wesley.

Python Software Foundation. (2025). *concurrent.futures — Launching parallel
tasks*. https://docs.python.org/3/library/concurrent.futures.html
