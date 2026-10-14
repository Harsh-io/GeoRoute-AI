"""Pytest configuration ensuring backend directory is in sys.path."""

from pathlib import Path
import sys

# Add backend directory to sys.path so that 'app' and 'georoute' can be imported cleanly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
