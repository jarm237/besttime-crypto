#!/usr/bin/env python3
"""Convenience wrapper for the fresh training-data fetcher."""

from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "scripts" / "fetch_fresh_training_data.py"
    sys.argv[0] = str(script_path)
    runpy.run_path(str(script_path), run_name="__main__")
