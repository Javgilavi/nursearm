#!/usr/bin/env python
"""Run the one-time Google Calendar OAuth consent.

Equivalent to ``uv run nursearm-calendar-auth``; kept here so it is discoverable
alongside the other helper scripts.
"""

from __future__ import annotations

import sys

from nursearm.integrations.calendar_auth import main

if __name__ == "__main__":
    sys.exit(main())
