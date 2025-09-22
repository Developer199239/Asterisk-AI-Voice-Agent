#!/bin/bash
# Wrapper around the Python-based model setup utility.
set -e
python3 scripts/model_setup.py "$@"
