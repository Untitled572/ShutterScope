# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Untitled572
"""Run the regression suite and require all fixtures to be exercised."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped:
    print("Required regression cases were skipped:", result.skipped, file=sys.stderr)
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
