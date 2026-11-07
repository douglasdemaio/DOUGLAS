#!/usr/bin/env bash
# Thin wrapper so AGENTS.md's `scripts/train.sh` entry point exists.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec "${PYTHON:-python3}" -m scripts.submit_job "$@"
