#!/usr/bin/env python3
"""Run from a skill checkout without requiring a package installation."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pano_reframe.cli import entrypoint
entrypoint()
