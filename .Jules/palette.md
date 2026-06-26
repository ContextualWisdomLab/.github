## Performance Optimizations
- **Embedded Python Scripts:** When optimizing embedded Python scripts inside shell scripts, you can extract the Python code to benchmark it efficiently before pasting it back.
- **I/O Caching:** Introducing a module-level dictionary to cache file contents (e.g. `_file_cache: dict[Path, list[str]] = {}`) is a quick and highly effective method to prevent repeated disk access when iterating over file findings.
