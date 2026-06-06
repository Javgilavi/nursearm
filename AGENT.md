# AGENT.md - the NurseArm orchestrator

The orchestrator is the decision-making layer between the browser and the MCP tools.
MCP discovers and executes capabilities; it does not decide what to do.

## Runtime architecture

```text
Browser text chat
      |
      v
FastAPI interface
      |
      v
OllamaMCPAgent (Qwen3:4b by default)
      |
      v
NurseArmMCPClient
      |
      v
NurseArm MCP server
      |
      v
SkillRegistry -> primitive or VLA skill -> RobotController
```

The browser never receives model credentials or direct robot access. The default model
runs locally through Ollama at `http://127.0.0.1:11434`, so the UI requires no paid API
key or external model token.

## Responsibilities

### FastAPI interface

`nursearm/interface/server.py` owns application startup, the audit log, the local agent,
and one persistent stdio MCP connection. Starting the interface automatically starts
the NurseArm MCP subprocess and closes it during shutdown.

### Orchestrator

`nursearm/orchestrator/ollama_agent.py`:

1. receives one user message,
2. discovers current MCP tools,
3. converts their schemas to Ollama function tools,
4. sends the request and tools to the local model,
5. executes requested tools through the MCP client,
6. feeds structured results back to the model,
7. repeats until the model returns a final response,
8. enforces a maximum turn count and writes audit events.

`nursearm/orchestrator/judge.py` remains a compatibility import for the active local
orchestrator.

### MCP client

`nursearm/mcp/client.py` only manages MCP transport and protocol operations:

- initialize the local stdio session,
- list tools,
- call tools,
- decode structured results.

It contains no model-specific reasoning. This keeps the MCP client reusable with
Ollama, Codex, OpenClaw, Claude Desktop, or another model host.

### MCP server

`nursearm/mcp/server.py` is the canonical capability boundary. It exposes task-level
tools and dispatches approved actions through `SkillRegistry`. It never exposes raw
joints, arbitrary shell commands, or direct motor access.

## Local model

The default configuration is:

```text
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
```

Qwen3:4b is a practical starting point for local tool selection. Larger local models
can improve planning but require more VRAM/RAM. Switching the model does not change MCP
or robot code.

## Safety rules

- The model may invoke only tools exposed by the MCP server.
- Tool arguments are validated by the MCP schema and skill implementation.
- The model must not report success until a tool returns success.
- Medication and human-contact tasks require explicit confirmation and deterministic
  checks in the skill layer.
- Joint limits, workspace limits, collision checks, and emergency stop behavior belong
  in `RobotController`, never in the language model.
- The LLM is task-level only and must not run the real-time robot control loop.

## External model clients

The same MCP server can run independently over Streamable HTTP:

```bash
NURSEARM_MOCK=1 uv run nursearm-mcp --transport streamable-http
```

Codex, MCP Inspector, OpenClaw, or another compatible client can connect to
`http://127.0.0.1:8000/mcp`. Those clients provide their own orchestration; the browser
continues to use the local Ollama orchestrator.

## Current test capabilities

The dummy MCP skills are intentionally safe and never move hardware:

- `skill1_check_environment` -> `skill1 completed`
- `skill2_prepare_assistance` -> `skill2 completed`
- `skill3_confirm_handoff` -> `skill3 completed`

Replace or disable them as real perception, primitive, and VLA skills become reliable.
