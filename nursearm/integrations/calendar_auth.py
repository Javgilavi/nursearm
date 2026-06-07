"""One-time Google OAuth consent for the medication scheduler.

Prerequisites:
  1. uv sync --extra calendar
  2. In Google Cloud Console: enable the Google Calendar API, create an OAuth client
     of type "Desktop app", download the JSON, and save it at the repo root as
     ``credentials.json``.

Then run once:
  uv run nursearm-calendar-auth

A browser window opens for consent and ``token.json`` is written next to
``credentials.json``. Restart ``nursearm-serve`` afterwards to pick up the connection.
"""

from __future__ import annotations

import sys

from nursearm.integrations.google_calendar import CREDENTIALS_PATH, SCOPES, TOKEN_PATH


def main() -> int:
    if not CREDENTIALS_PATH.exists():
        print(f"Missing {CREDENTIALS_PATH}")
        print(
            "Create an OAuth client (Desktop app) in Google Cloud Console, enable the\n"
            "Google Calendar API, download the JSON, and save it as credentials.json."
        )
        return 1
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Google libraries missing. Install them with: uv sync --extra calendar")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    print(f"Authorized. Wrote {TOKEN_PATH}")
    print("Restart nursearm-serve to connect the medication scheduler to your calendar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
