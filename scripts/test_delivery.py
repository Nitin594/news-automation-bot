#!/usr/bin/env python3
"""Convenience script to test delivery channels."""

import os
import sys

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from daily_tech_brief.config import get_settings
from daily_tech_brief.scheduler import WorkflowCoordinator
from daily_tech_brief.main import cmd_test_delivery
import argparse

if __name__ == "__main__":
    settings = get_settings()
    coordinator = WorkflowCoordinator(settings)
    args = argparse.Namespace()
    sys.exit(cmd_test_delivery(coordinator, args))
