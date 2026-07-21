"""Pytest configuration: put src/ on sys.path so `ed_ops` is importable.

Mirrors the layout of sibling portfolio projects where src/ is the source
root but is not pip-installed during local development.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
