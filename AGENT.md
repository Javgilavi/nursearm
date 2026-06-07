# NurseArm Agent

The browser sends text to either `OllamaMCPAgent` or `ClaudeMCPAgent`. The selected
agent discovers MCP tools, calls only those tools, appends the structured result to
its conversation, and returns a concise response.

```text
Browser -> FastAPI -> Ollama or Claude agent -> MCP client -> MCP server
                                                        -> SkillRegistry
                                                        -> RobotController
```

The active tool boundary is:

- `list_skills`: inspect enabled capabilities
- `get_scene`: read implemented hand/palm state
- `run_skill`: execute a named primitive or ACT skill
- `handover_pill`: execute the pill-handover policy for `green` or `black`

For `handover_pill`, the agent must pass exactly one supported color:
`{"color":"green"}` or `{"color":"black"}`.

The agent must not claim success unless the returned `SkillResult.success` is true.
The LLM does not receive raw motor access and does not run the real-time control loop.

Conversation history is kept in memory for the server process. Agent and tool events
are appended to `data/audit/<session>.jsonl`.

## Backends

Ollama is the default:

```text
AGENT_BACKEND=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
```

Claude requires:

```text
AGENT_BACKEND=claude
ANTHROPIC_API_KEY=...
CLAUDE_MODEL=claude-sonnet-4-6
```

Both backends enforce a maximum of 12 model turns per user request.

## Safety Boundary

- Skill names and arguments are validated through MCP schemas and the registry.
- Learned policy execution is isolated in a `lerobot-rollout` subprocess.
- Robot limits, collision handling, authentication, and emergency-stop behavior must
  be enforced below the LLM layer.
- Mock mode prevents hardware access but does not fabricate ACT success.

See the limitations in [README.md](README.md) before using real hardware.
