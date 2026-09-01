#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from ustc_notice_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1:])