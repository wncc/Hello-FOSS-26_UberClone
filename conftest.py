"""Let tests import the backend package (`app`) when run from the repo root."""

import sys
from pathlib import Path

BACKEND = str(Path(__file__).parent / "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)