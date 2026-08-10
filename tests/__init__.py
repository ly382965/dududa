from __future__ import annotations

import sys
from pathlib import Path


PLUGIN_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "apps" / "astrbot-plugins"
if str(PLUGIN_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SOURCE_ROOT))
