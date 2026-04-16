"""
Vercel FastAPI entrypoint.

Vercel detects FastAPI apps by scanning for a top-level variable named `app`
in one of the standard entrypoint filenames (including `main.py`).
"""

from backend.main import app  # noqa: F401

