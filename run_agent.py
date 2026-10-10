#!/usr/bin/env python3
"""Entry point. Double-clicking the packaged .exe lands here."""
import sys
from sectorloom_agent.app import main

if __name__ == "__main__":
    sys.exit(main())
