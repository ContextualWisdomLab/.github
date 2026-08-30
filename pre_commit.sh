#!/bin/bash
# Pre-commit step to run tests and make sure coverage is met
PYTHONPATH=$PWD python3 -m pytest tests/test_agent_mention_sweep.py --cov=scripts/ci/agent_mention_sweep.py
