"""FastAPI backend for the NurseArm operator UI.

Endpoints:
  GET  /                -> the web UI
  GET  /static/{path}   -> static files (app.js, styles.css)
  GET  /state           -> current status + scene summary
  GET  /scene           -> current RGB-D scene summary
  GET  /frame           -> latest camera frame as PNG
  POST /chat            -> {"text": ...}; runs local Ollama agent via MCP, returns reply
  WS   /audit           -> streams audit events live
  GET  /health          -> liveness + Ollama model status

Run locally in mock mode:
    NURSEARM_MOCK=1 uvicorn nursearm.interface.server:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from nursearm.audit.log import AuditLog
from nursearm.mcp.client import NurseArmMCPClient
from nursearm.orchestrator.ollama_agent import OllamaMCPAgent, OllamaUnavailableError
from nursearm.orchestrator.skill_registry import SkillRegistry
from nursearm.perception.realsense import Perception
from nursearm.robot.controller import RobotController
from nursearm.types import SceneObservation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MOCK = os.getenv("NURSEARM_MOCK", "0") == "1"
WEB_DIR = Path(__file__).resolve().parent / "web"


class ChatIn(BaseModel):
    text: str


class AppState:
    """Long-lived application singletons."""

    def __init__(self) -> None:
        self.audit = AuditLog()
        self.robot = RobotController(mock=MOCK)
        self.perception = Perception(mock=MOCK)
        self.skills = SkillRegistry()
        self.mcp = NurseArmMCPClient()
        self.agent: OllamaMCPAgent | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ws_clients: set[WebSocket] = set()
        self._latest_scene: SceneObservation | None = None
        self._latest_frame: np.ndarray | None = None
        self.audit.subscribe(self._broadcast)

    async def start(self) -> None:
        await self.mcp.connect()
        self.agent = OllamaMCPAgent(self.mcp, audit=self.audit)

    async def close(self) -> None:
        if self.agent is not None:
            await self.agent.close()
        await self.mcp.close()
        self.robot.disconnect()
        self.perception.close()

    def _broadcast(self, event: dict[str, Any]) -> None:
        if self.loop is None:
            return
        for ws in list(self._ws_clients):
            asyncio.run_coroutine_threadsafe(ws.send_json(event), self.loop)

    def get_scene_summary(self) -> dict[str, Any]:
        try:
            scene = self.perception.observe()
        except Exception as exc:
            logger.exception("scene observation failed")
            self._latest_scene = None
            self._latest_frame = None
            return {"ok": False, "error": str(exc), "mock": MOCK, "scene": None}
        self._latest_scene = scene
        self._latest_frame = scene.frame
        payload = scene.summary()
        payload["ok"] = True
        payload["mock"] = MOCK
        return payload

    def get_state(self) -> dict[str, Any]:
        scene = self.get_scene_summary()
        return {
            "ok": True,
            "mock": MOCK,
            "robot_connected": self.robot.mock or bool(getattr(self.robot, "_robot", None)),
            "camera_connected": scene.get("ok", False),
            "skills": [
                {"name": info.name, "description": info.description, "kind": info.kind}
                for info in self.skills.info()
            ],
            "scene": scene,
            "audit_count": len(self.audit.read_all()),
        }

    def get_frame_png(self) -> bytes:
        color = self._latest_frame
        if color is None:
            try:
                color, _ = self.perception.frames()
            except Exception as exc:
                logger.exception("frame capture failed")
                color = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    color,
                    f"Camera unavailable: {exc}",
                    (24, 240),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                return self._encode_png(color)
        if color is None or color.size == 0:
            color = np.zeros((480, 640, 3), dtype=np.uint8)
        if self.perception.mock and not self.perception.has_real_camera:
            color = self._make_mock_frame(color)
        return self._encode_png(color)

    @staticmethod
    def _make_mock_frame(color: np.ndarray) -> np.ndarray:
        frame = color.copy()
        frame[:] = (28, 24, 34)
        cv2.rectangle(frame, (40, 60), (600, 420), (78, 64, 48), thickness=-1)
        cv2.rectangle(frame, (80, 110), (280, 350), (214, 70, 40), thickness=-1)
        cv2.rectangle(frame, (360, 140), (540, 280), (55, 120, 222), thickness=-1)
        cv2.rectangle(frame, (320, 360), (560, 430), (46, 122, 82), thickness=-1)
        cv2.putText(frame, "Mock RealSense RGB-D feed", (56, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (234, 235, 240), 2)
        cv2.putText(frame, "Coke can", (104, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, "Cup", (420, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(frame, "Notebook", (380, 405), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        return frame

    @staticmethod
    def _encode_png(frame: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("failed to encode camera frame")
        return buf.tobytes()


state: AppState | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = AppState()
    state.loop = asyncio.get_running_loop()
    await state.start()
    logger.info("NurseArm ready (mock=%s).", MOCK)
    try:
        yield
    finally:
        await state.close()


app = FastAPI(title="NurseArm", lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/static/{path:path}")
async def static_file(path: str) -> FileResponse:
    return FileResponse(WEB_DIR / path)


@app.get("/health")
async def health() -> dict[str, Any]:
    ollama = await state.agent.model_status() if state.agent else {"available": False}
    return {"ok": True, "mock": MOCK, "ollama": ollama}


@app.get("/state")
async def state_view() -> dict[str, Any]:
    return state.get_state()


@app.get("/scene")
async def scene_view() -> dict[str, Any]:
    return state.get_scene_summary()


@app.get("/frame")
async def frame_view() -> Response:
    return Response(content=state.get_frame_png(), media_type="image/png")


@app.post("/chat")
async def chat(msg: ChatIn) -> dict[str, str]:
    try:
        reply = await state.agent.handle(msg.text)
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"reply": reply}


@app.websocket("/audit")
async def audit_ws(ws: WebSocket) -> None:
    await ws.accept()
    state._ws_clients.add(ws)
    try:
        for record in state.audit.read_all():
            await ws.send_json(record)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state._ws_clients.discard(ws)


def main() -> None:
    import uvicorn

    uvicorn.run("nursearm.interface.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
