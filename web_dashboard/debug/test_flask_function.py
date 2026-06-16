#!/usr/bin/env python3
"""Deprecated wrapper — use debug_performance_chart_data.py instead."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "debug_performance_chart_data.py"
    print(f"Note: {Path(__file__).name} is deprecated; running {target.name}\n")
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
