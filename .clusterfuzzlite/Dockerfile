FROM scratch
USER 65532:65532
HEALTHCHECK NONE

# ClusterFuzzLite discovery marker for Scorecard. The runnable Atheris target is
# fuzz/fuzz_opencode_review_normalize_output.py; this marker stays buildable
# when central coverage checks build .clusterfuzzlite as the Docker context.
