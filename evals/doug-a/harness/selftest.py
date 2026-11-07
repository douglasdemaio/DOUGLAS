"""Runnable harness self-test: python evals/doug-a/harness/selftest.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grader  # noqa: E402

if __name__ == "__main__":
    sys.exit(grader.main())
