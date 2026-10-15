FROM ghcr.io/actions/actions-runner@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16 postgresql-client-16 libpq-dev python3-venv ca-certificates git curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER runner
WORKDIR /home/runner
