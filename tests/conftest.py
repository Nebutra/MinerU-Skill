"""Make the single-file ``scripts/mineru.py`` importable as ``mineru``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
