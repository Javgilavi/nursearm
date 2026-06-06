# NurseArm MCP setup

NurseArm uses MCP as the canonical interface between an LLM agent and the approved
robot skills. Keep `NURSEARM_MOCK=1` during these tests so no hardware can move.

## Install

```bash
cd /home/jgilaviles/nursearm
uv sync --extra dev
cp .env.example .env
```

Only the Claude-backed tests require `ANTHROPIC_API_KEY` in `.env`.

## Offline test

This starts the MCP server over stdio, discovers its tools, and calls all three dummy
skills without contacting an LLM:

```bash
NURSEARM_MOCK=1 uv run python scripts/test_mcp.py
```

Expected output:

```text
PASS skill1_check_environment: skill1 completed
PASS skill2_prepare_assistance: skill2 completed
PASS skill3_confirm_handoff: skill3 completed
```

## Manual client

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp-client --list-tools

NURSEARM_MOCK=1 uv run nursearm-mcp-client \
  --call skill2_prepare_assistance \
  --arguments '{"request":"prepare to help me"}'
```

## Claude through NurseArm

Set `ANTHROPIC_API_KEY` in `.env`, then run:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp-client \
  --chat "Please inspect the room before helping me"
```

Claude receives the schemas discovered from MCP and should select
`skill1_check_environment`.

The browser UI uses the same MCP client:

```bash
NURSEARM_MOCK=1 uv run uvicorn nursearm.interface.server:app --reload
```

Open `http://127.0.0.1:8000`.

The interface starts `python -m nursearm.mcp.server` automatically over stdio and
closes it during FastAPI shutdown. You do not need a second MCP terminal for the UI.

## Connect Codex

For Codex, run NurseArm as a standalone Streamable HTTP server:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp --transport streamable-http
```

In another terminal, register it once:

```bash
codex mcp add nursearm --url http://127.0.0.1:8000/mcp
codex mcp list
```

Then start Codex:

```bash
codex
```

Example prompt:

```text
Use the NurseArm MCP server. List its skills and run
skill1_check_environment with request "inspect the room".
```

The expected result is `skill1 completed`. OAuth discovery `404` messages are
harmless; successful `POST /mcp` and `ListToolsRequest` entries confirm the connection.

Alternatively, let Codex launch the stdio server itself:

```bash
codex mcp add --env NURSEARM_MOCK=1 nursearm -- \
  /home/jgilaviles/nursearm/.venv/bin/python -m nursearm.mcp.server
```

With the stdio registration, do not start `nursearm-mcp` separately.

## MCP Inspector

Run the server with Streamable HTTP:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp --transport streamable-http
```

In another terminal:

```bash
npx -y @modelcontextprotocol/inspector
```

Connect the Inspector to `http://127.0.0.1:8000/mcp`.

The standalone HTTP server and web interface both default to port `8000`. Stop the
interface first, or use stdio, before starting this server.

## Claude Desktop or another stdio host

Add this local process through the application's MCP developer settings:

```json
{
  "mcpServers": {
    "nursearm": {
      "command": "/home/jgilaviles/nursearm/.venv/bin/python",
      "args": ["-m", "nursearm.mcp.server"],
      "env": {
        "NURSEARM_MOCK": "1"
      }
    }
  }
}
```

Restart the desktop application, inspect its connected tools, and ask:

```text
Inspect the room using NurseArm.
```

The expected tool result is `skill1 completed`.

## Architecture

```text
Browser or desktop LLM
        |
        v
Claude/model host -> MCP client -> NurseArm MCP server
                                      |
                                      v
                                SkillRegistry
                                 |         |
                              dummy     real skills
                                            |
                                            v
                                      RobotController
```

The MCP server exposes task-level tools only. It does not expose raw joints or motors.
