#!/bin/sh
set -e

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY is not set}"
: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN is not set}"

mkdir -p /root/.openclaw/workspace
cp -n /app/workspace/SOUL.md /root/.openclaw/workspace/SOUL.md 2>/dev/null || true

# Write a valid openclaw.json — channels are registered separately via CLI
python3 - <<PYEOF
import json, os, pathlib, secrets

config = {
    "gateway": {
        "mode": "local",
        "auth": {
            "mode": "token",
            "token": os.environ.get("OPENCLAW_GATEWAY_TOKEN", secrets.token_hex(24)),
        },
    },
    "models": {
        "providers": {
            "anthropic": {
                "apiKey": os.environ["ANTHROPIC_API_KEY"],
            }
        }
    },
    "mcp": {
        "servers": {
            "nursearm": {
                "command": "python3",
                "args": ["/app/mcp_bridge.py"],
                "env": {
                    "NURSEARM_URL": os.environ.get("NURSEARM_URL", "http://host.docker.internal:8000")
                }
            }
        }
    },
    "tools": {
        "deny": ["shell", "exec", "computer", "browser", "read", "write",
                 "edit", "glob", "grep", "ls", "cron", "rm", "mv", "cp"]
    },
}

pathlib.Path("/root/.openclaw").mkdir(parents=True, exist_ok=True)
path = pathlib.Path("/root/.openclaw/openclaw.json")
path.write_text(json.dumps(config, indent=2))
path.chmod(0o600)
print(f"openclaw.json written")
PYEOF

# Register Telegram bot token via the CLI (this writes to credentials store, not openclaw.json)
echo "Registering Telegram channel…"
openclaw channels add --channel telegram --token "$TELEGRAM_BOT_TOKEN" 2>&1

# Fix up any remaining schema issues and create required dirs
echo "Running openclaw doctor --fix…"
openclaw doctor --fix 2>&1 | grep -E "Doctor changes|Removed|Migration|CRITICAL|error" || true

# Set the model
echo "Setting model…"
openclaw models set "anthropic/claude-sonnet-4-6" 2>&1 || true

echo "Starting OpenClaw gateway…"
exec openclaw gateway
