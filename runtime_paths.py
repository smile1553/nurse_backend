"""Writable deployment files live beside the executable, never in its bundle."""
import sys
from pathlib import Path


BASE_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent)
