#!/usr/bin/env python3
"""Root entrypoint script for Daily Tech Brief."""

import os
import sys

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from daily_tech_brief.main import main

if __name__ == "__main__":
    sys.exit(main())
