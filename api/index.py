import os
import sys

# Ensure project root is importable on Vercel.
# Vercel's working directory depends on "Root Directory" setting.
# Support both layouts:
# - repo root == Calling/ (backend/ is directly under root)
# - repo root contains Calling/ (backend/ is under Calling/backend)
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
CANDIDATES = [
    REPO_ROOT,
    os.path.join(REPO_ROOT, "Calling"),
]
for p in CANDIDATES:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.main import app  # type: ignore  # noqa: E402
except Exception as e:  # pragma: no cover
    # Make the real import error visible in Vercel logs.
    import traceback

    traceback.print_exc()
    raise e

