"""FastAPI backend: chat in, judge runs, audit log streams out.

Endpoints:
  GET  /            -> the minimal web UI (chat + live audit log)
  POST /chat        -> {"text": ...} ; runs the judge, returns its final reply
  WS   /audit       -> streams every audit event live (judge reasoning + robot actions)
  GET  /health      -> liveness

Run with mock hardware on a laptop:
    NURSEARM_MOCK=1 uvicorn nursearm.interface.server:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from nursearm.audit.log import AuditLog
from nursearm.integrations.calendar import make_calendar_client
from nursearm.orchestrator.judge import Judge
from nursearm.orchestrator.recovery import RecoveryManager
from nursearm.orchestrator.skill_registry import SkillRegistry
from nursearm.perception.realsense import Perception
from nursearm.robot.controller import RobotController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MOCK = os.getenv("NURSEARM_MOCK", "0") == "1"
WEB_DIR = Path(__file__).resolve().parent / "web"


class ChatIn(BaseModel):
    text: str


class App:
    """Holds the long-lived singletons (robot, perception, judge, audit)."""

    def __init__(self) -> None:
        self.audit = AuditLog()
        self.robot = RobotController(mock=MOCK)
        self.perception = Perception(mock=MOCK)
        self.skills = SkillRegistry()
        self.recovery = RecoveryManager()
        self.calendar = make_calendar_client()
        self.loop = asyncio.get_event_loop()
        self._ws_clients: set[WebSocket] = set()
        self.audit.subscribe(self._broadcast)
        self.judge = Judge(self.skills, self.perception, self.robot, self.audit,
                           self.recovery, self.calendar, speak_fn=self._speak)

    def _speak(self, text: str) -> None:
        from nursearm.interface import voice

        voice.say(text)

    def _broadcast(self, event: dict) -> None:
        for ws in list(self._ws_clients):
            asyncio.run_coroutine_threadsafe(ws.send_json(event), self.loop)


state: App | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = App()
    logger.info("NurseArm ready (mock=%s).", MOCK)
    yield
    state.robot.disconnect()
    state.perception.close()


app = FastAPI(title="NurseArm", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "mock": MOCK}


@app.post("/chat")
async def chat(msg: ChatIn) -> dict:
    # The judge loop is blocking (sync Anthropic calls + robot I/O) -> run off-thread.
    reply = await asyncio.to_thread(state.judge.handle, msg.text)
    return {"reply": reply}


@app.websocket("/audit")
async def audit_ws(ws: WebSocket) -> None:
    await ws.accept()
    state._ws_clients.add(ws)
    try:
        for record in state.audit.read_all():  # replay history on connect
            await ws.send_json(record)
        while True:
            await ws.receive_text()  # keep-alive; we only push
    except WebSocketDisconnect:
        pass
    finally:
        state._ws_clients.discard(ws)
