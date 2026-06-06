# NurseArm MCP setup

NurseArm uses MCP as the canonical interface between an LLM agent and the approved
robot skills. Keep `NURSEARM_MOCK=1` during these tests so no hardware can move.

## Install

```bash
cd /home/jgilaviles/nursearm
uv sync --extra dev
cp .env.example .env
```

The browser agent uses local Ollama and requires no external API key or paid tokens.

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

## Local Qwen agent through NurseArm

Install Ollama, pull the default model, and verify it responds:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:4b
ollama run qwen3:4b "Reply with: model ready"
```

Ollama normally runs as a local service. If it is not running, start it in another terminal:

```bash
ollama serve
```

Start the browser UI:

```bash
NURSEARM_MOCK=1 uv run uvicorn nursearm.interface.server:app --reload
```

Open `http://127.0.0.1:8000`. FastAPI connects to Ollama at
`http://127.0.0.1:11434`, starts the NurseArm MCP server automatically over stdio,
and closes that MCP subprocess during shutdown. No second MCP terminal is needed.

The defaults are configured in `.env`:

```text
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
```

Other no-token local options:

| Option | Use when |
|---|---|
| `qwen3:4b` through Ollama | Default balance for this laptop and MCP tool selection |
| `qwen3:8b` through Ollama | Better reasoning with higher latency and memory use |
| A 2B tool-capable model through Ollama | Lower-memory or CPU-only development |
| LM Studio | You want a GUI for downloading and comparing local models |
| llama.cpp | You want direct GGUF deployment and tighter runtime control |

The current backend speaks Ollama's `/api/chat` format. LM Studio or llama.cpp can still
use the same MCP server, but need their own agent adapter or an Ollama-compatible proxy.

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
Browser local agent or desktop LLM
        |
        v
Ollama/model host -> MCP client -> NurseArm MCP server
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
