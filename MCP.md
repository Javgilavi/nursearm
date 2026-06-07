# NurseArm MCP

NurseArm exposes one bounded MCP server implemented in `nursearm/mcp/server.py`.

## Local Smoke Test

```bash
NURSEARM_MOCK=1 uv run python scripts/test_mcp.py
```

The script verifies tool discovery, the exact enabled skill registry, and a safe mock
`home` command.

## CLI Client

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp-client --list-tools

NURSEARM_MOCK=1 uv run nursearm-mcp-client \
  --call run_skill \
  --arguments '{"name":"move_right","args":{"step_m":0.02}}'

NURSEARM_MOCK=1 uv run nursearm-mcp-client \
  --call handover_pill \
  --arguments '{"color":"green"}'
```

## Streamable HTTP

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp --transport streamable-http
```

The endpoint is `http://127.0.0.1:8000/mcp`.

Register it with Codex:

```bash
codex mcp add nursearm --url http://127.0.0.1:8000/mcp
```

Or let Codex start the stdio server:

```bash
codex mcp add --env NURSEARM_MOCK=1 nursearm -- \
  /home/jgilaviles/nursearm/.venv/bin/python -m nursearm.mcp.server
```

## Claude Desktop

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

## Tools

| Tool | Description |
|---|---|
| `list_skills` | Return every enabled registry skill |
| `get_scene` | Return hand openness, palm point, palm-up state, and confidence |
| `run_skill` | Execute an enabled skill by name |
| `handover_pill` | Run the pill handover ACT policy for `green` or `black` |

The server does not expose shell commands or raw motor registers.
