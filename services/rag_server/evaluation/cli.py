"""Deprecated CLI shim for evaluation v1.

Use: python -m evaluation_v2.cli ...
"""

from evaluation_v2.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
