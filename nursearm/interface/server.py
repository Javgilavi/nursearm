"""FastAPI backend for the NurseArm operator UI.

Endpoints:
  GET  /                -> the web UI
  GET  /static/{path}   -> static files (app.js, styles.css)
  GET  /state           -> current status + scene summary
  GET  /scene           -> current RGB-D scene summary
  GET  /stream          -> MJPEG live camera stream (browser-native, no JS polling)
  GET  /frame           -> single latest JPEG frame
  POST /chat            -> {"text": ...}; runs local Ollama agent via MCP, returns reply
  POST /transcribe      -> audio file upload; returns {"text": ...} via Faster-Whisper
  WS   /audit           -> streams audit events live
  GET  /health          -> liveness + Ollama model status

Run locally in mock mode:
    NURSEARM_MOCK=1 uvicorn nursearm.interface.server:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TYPE_CHECKING

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

from nursearm.audit.log import AuditLog
from nursearm.mcp.client import NurseArmMCPClient
from nursearm.orchestrator.claude_agent import ClaudeMCPAgent, ClaudeUnavailableError
from nursearm.orchestrator.ollama_agent import OllamaMCPAgent, OllamaUnavailableError
from nursearm.orchestrator.skill_registry import SkillRegistry
from nursearm.perception.realsense import Perception
from nursearm.robot.controller import RobotController
from nursearm.types import SceneObservation

AGENT_BACKEND = os.getenv("AGENT_BACKEND", "ollama").lower()  # "ollama" | "claude"

class _NoiseFilter(logging.Filter):
    """Drop repetitive 404s from external tools polling our server."""
    _SKIP = ("/api/boxes/", "/ws/robot_state")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(pat in msg for pat in self._SKIP)


logging.basicConfig(level=logging.INFO)
logging.getLogger("uvicorn.access").addFilter(_NoiseFilter())
logger = logging.getLogger(__name__)

MOCK = os.getenv("NURSEARM_MOCK", "0") == "1"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WEB_DIR = Path(__file__).resolve().parent / "web"

_JPEG_PARAMS = [cv2.IMWRITE_JPEG_QUALITY, 75]
_BLANK_FRAME = np.zeros((480, 640, 3), dtype=np.uint8)


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
        self.agent: OllamaMCPAgent | ClaudeMCPAgent | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ws_clients: set[WebSocket] = set()
        self._latest_scene: SceneObservation | None = None
        self._latest_jpg: bytes = self._encode_jpg(_BLANK_FRAME)
        self._latest_palm_jpg: bytes = self._encode_jpg(_BLANK_FRAME)
        self._latest_palm_result: dict = {"detected": False}
        self._palm_log_tick: int = 0
        self._camera_task: asyncio.Task | None = None
        self._whisper: WhisperModel | None = None
        self._whisper_lock = asyncio.Lock()
        self.audit.subscribe(self._broadcast)

    async def start(self) -> None:
        await self.mcp.connect()
        if AGENT_BACKEND == "claude":
            self.agent = ClaudeMCPAgent(self.mcp, audit=self.audit)
            logger.info("Agent backend: Claude (%s)", os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))
        else:
            self.agent = OllamaMCPAgent(self.mcp, audit=self.audit)
            logger.info("Agent backend: Ollama")
        self._camera_task = asyncio.create_task(self._camera_loop())
        asyncio.create_task(self._preload_whisper())

    async def close(self) -> None:
        if self._camera_task is not None:
            self._camera_task.cancel()
        if self.agent is not None:
            await self.agent.close()
        await self.mcp.close()
        self.robot.disconnect()
        self.perception.close()

    # -- camera background task --------------------------------------------------

    async def _camera_loop(self) -> None:
        """Continuously capture from the camera and store the latest JPEG."""
        while True:
            try:
                raw_jpg, palm_jpg = await asyncio.to_thread(self._capture_both_jpg)
                self._latest_jpg = raw_jpg
                self._latest_palm_jpg = palm_jpg
            except Exception as exc:
                logger.debug("camera capture error: %s", exc)
            await asyncio.sleep(1 / 30)  # target 30 fps capture

    def _capture_both_jpg(self) -> tuple[bytes, bytes]:
        """Capture one frame and return (raw_jpg, palm_overlay_jpg)."""
        try:
            color, depth = self.perception.frames()
        except Exception:
            color, depth = None, None
        if color is None or color.size == 0:
            color = _BLANK_FRAME.copy()
        if depth is None or not isinstance(depth, np.ndarray) or depth.size == 0:
            depth = np.zeros(color.shape[:2], dtype=np.float32)
        if self.perception.mock and not self.perception.has_real_camera:
            color = self._make_mock_frame(color)
        raw_jpg = self._encode_jpg(color)
        palm_jpg = self._encode_jpg(self._draw_palm(color, depth))
        return raw_jpg, palm_jpg

    def _draw_palm(self, color: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """Run palm detection, log result every ~2 s, return annotated frame."""
        from nursearm.perception import hands
        self._palm_log_tick = (self._palm_log_tick + 1) % 60  # log every 60 frames ≈ 2 s
        should_log = self._palm_log_tick == 0
        try:
            debug = hands.analyze(self.perception, color=color, depth=depth)
            if debug is not None:
                self._latest_palm_result = {
                    "detected": True,
                    "handedness": debug.handedness,
                    "is_open": debug.is_open,
                    "openness_score": round(float(debug.openness_score), 2),
                    "palm_up": debug.palm_up,
                    "palm_up_confidence": round(float(debug.palm_up_confidence), 2),
                }
                if should_log:
                    logger.info(
                        "Palm ✋ %s | %s | palm-up: %s (%.0f%%)",
                        debug.handedness or "?",
                        "open" if debug.is_open else "closed",
                        "yes" if debug.palm_up else "no",
                        debug.palm_up_confidence * 100,
                    )
                return hands.draw_debug(color.copy(), debug)
            else:
                self._latest_palm_result = {"detected": False}
                if should_log:
                    logger.info("Palm: no hand in frame")
        except Exception as exc:
            logger.warning("Palm detection error: %s", exc)
            self._latest_palm_result = {"detected": False, "error": str(exc)}
        return color.copy()

    @staticmethod
    def _encode_jpg(frame: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", frame, _JPEG_PARAMS)
        return bytes(buf) if ok else b""

    # -- speech-to-text ----------------------------------------------------------

    async def _preload_whisper(self) -> None:
        try:
            await self.get_whisper()
        except Exception as exc:
            logger.warning("Whisper preload failed: %s", exc)

    async def get_whisper(self) -> "WhisperModel":
        async with self._whisper_lock:
            if self._whisper is None:
                self._whisper = await asyncio.to_thread(self._load_whisper)
        return self._whisper

    @staticmethod
    def _load_whisper() -> "WhisperModel":
        from faster_whisper import WhisperModel  # noqa: PLC0415
        # RTX 5070 (Blackwell sm_120) crashes with int8 — always use float16 on CUDA.
        try:
            model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
            logger.info("Faster-Whisper loaded (%s, cuda/float16).", WHISPER_MODEL)
        except Exception:
            model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
            logger.info("Faster-Whisper loaded (%s, cpu/int8).", WHISPER_MODEL)
        return model

    async def transcribe_audio(self, data: bytes, suffix: str = ".webm") -> str:
        model = await self.get_whisper()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            tmp_path = f.name
        try:
            def _run() -> str:
                # Consume the lazy generator inside this thread — do not return it.
                segments, _ = model.transcribe(tmp_path, beam_size=5, vad_filter=True, language="en")
                return " ".join(s.text.strip() for s in segments).strip()
            return await asyncio.to_thread(_run)
        finally:
            os.unlink(tmp_path)

    # -- scene / state -----------------------------------------------------------

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
            return {"ok": False, "error": str(exc), "mock": MOCK, "scene": None}
        self._latest_scene = scene
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


state: AppState | None = None
_ngrok_url: str | None = None


def _ensure_ollama() -> None:
    """Start `ollama serve` in the background if it is not already running."""
    import httpx
    try:
        httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0)
        logger.info("Ollama already running.")
        return
    except Exception:
        pass
    logger.info("Starting Ollama in the background...")
    subprocess.Popen(  # noqa: S603
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(0.5)
        try:
            httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0)
            logger.info("Ollama is up.")
            return
        except Exception:
            pass
    logger.warning("Ollama did not become ready in 10 s; continuing anyway.")


def _ensure_ngrok(port: int = 8000) -> str | None:
    """Start ngrok if not running and return the public HTTPS URL. No-op if ngrok is not installed."""
    import shutil
    import httpx

    if not shutil.which("ngrok"):
        return None

    # Already running? Just grab the URL.
    try:
        r = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=1.0)
        for t in r.json().get("tunnels", []):
            if t.get("proto") == "https":
                return t["public_url"]
    except Exception:
        pass

    logger.info("Starting ngrok tunnel on port %d...", port)
    subprocess.Popen(  # noqa: S603
        ["ngrok", "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        time.sleep(0.5)
        try:
            r = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=1.0)
            for t in r.json().get("tunnels", []):
                if t.get("proto") == "https":
                    return t["public_url"]
        except Exception:
            pass

    logger.warning("ngrok did not expose a tunnel in 10 s — phone access unavailable.")
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state, _ngrok_url
    if AGENT_BACKEND != "claude":
        await asyncio.to_thread(_ensure_ollama)
    _ngrok_url = await asyncio.to_thread(_ensure_ngrok)
    if _ngrok_url:
        logger.info("=" * 56)
        logger.info("  Phone / remote access:  %s", _ngrok_url)
        logger.info("=" * 56)
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
    return {"ok": True, "mock": MOCK, "ollama": ollama, "ngrok_url": _ngrok_url}


@app.get("/qr.svg")
async def qr_svg() -> Response:
    """SVG QR code for the active ngrok tunnel URL."""
    if not _ngrok_url:
        raise HTTPException(status_code=404, detail="No remote tunnel active")
    import io
    import segno
    qr = segno.make_qr(_ngrok_url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=5, border=2, dark="#236f7f", light="#ffffff")
    return Response(content=buf.getvalue(), media_type="image/svg+xml")


@app.get("/state")
async def state_view() -> dict[str, Any]:
    return state.get_state()


@app.get("/scene")
async def scene_view() -> dict[str, Any]:
    return state.get_scene_summary()


@app.get("/stream")
async def stream_view() -> StreamingResponse:
    """MJPEG stream — browsers display this natively in an <img> tag."""
    async def generate():
        while True:
            jpg = state._latest_jpg
            if jpg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpg
                    + b"\r\n"
                )
            await asyncio.sleep(1 / 25)  # push at 25 fps to browser

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@app.get("/stream/palm")
async def palm_stream_view() -> StreamingResponse:
    """MJPEG stream with palm-detection overlay (camera 1)."""
    async def generate():
        while True:
            jpg = state._latest_palm_jpg
            if jpg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpg
                    + b"\r\n"
                )
            await asyncio.sleep(1 / 25)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@app.get("/frame")
async def frame_view() -> Response:
    """Single latest JPEG frame (for snapshot use)."""
    return Response(content=state._latest_jpg, media_type="image/jpeg")


@app.get("/palm/status")
async def palm_status() -> dict[str, Any]:
    """Latest palm detection result — polled by the UI badge."""
    return state._latest_palm_result


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict[str, str]:
    """Transcribe uploaded audio (WebM/Opus or any ffmpeg format) via Faster-Whisper."""
    data = await audio.read()
    suffix = Path(audio.filename or "recording.webm").suffix or ".webm"
    try:
        text = await state.transcribe_audio(data, suffix=suffix)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Transcription failed: {exc}") from exc
    return {"text": text}


@app.post("/chat")
async def chat(msg: ChatIn) -> dict[str, str]:
    try:
        reply = await state.agent.handle(msg.text)
    except (OllamaUnavailableError, ClaudeUnavailableError) as exc:
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
