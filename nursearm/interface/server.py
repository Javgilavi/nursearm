"""FastAPI backend for the NurseArm operator UI.

Endpoints:
  GET  /                -> operator console (3D twin, motor graph, MCP chat, controls)
  GET  /console         -> patient console (palm detection, medication dispensing)
  GET  /business        -> business plan page
  GET  /landing         -> marketing landing page
  GET  /static/{path}   -> static files (app.js, styles.css, console.css, console.js)
  GET  /state           -> current status + scene summary
  GET  /scene           -> current RGB-D scene summary
  GET  /stream          -> MJPEG live camera stream (browser-native, no JS polling)
  GET  /frame           -> single latest JPEG frame
  POST /chat            -> {"text": ...}; runs local Ollama agent via MCP, returns reply
  POST /transcribe      -> audio file upload; returns {"text": ...} via Faster-Whisper
  POST /skills/handover-pill -> {"color": "green"|"black"}; run handover skill directly
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
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

from nursearm.audit.log import AuditLog
from nursearm.config import calendar_config
from nursearm.integrations.google_calendar import CalendarUnavailableError, build_client
from nursearm.integrations.scheduler import PillScheduler
from nursearm.mcp.client import NurseArmMCPClient
from nursearm.orchestrator.claude_agent import ClaudeMCPAgent, ClaudeUnavailableError
from nursearm.orchestrator.ollama_agent import OllamaMCPAgent, OllamaUnavailableError
from nursearm.orchestrator.skill_registry import SkillRegistry
from nursearm.perception.realsense import Perception
from nursearm.robot.controller import RobotController
from nursearm.types import SceneObservation

AGENT_BACKEND = os.getenv("AGENT_BACKEND", "ollama").lower()  # "ollama" | "claude"

class _NoiseFilter(logging.Filter):
    """Drop repetitive polling requests from the Uvicorn access log."""
    _SKIP = (
        "/api/boxes/",
        "/ws/robot_state",
        "GET /robot/state ",
        "GET /palm/status ",
        "GET /health ",
        "GET /qr.svg",
        "GET /calendar/schedule ",
        "GET /calendar/status ",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(pat in msg for pat in self._SKIP)


logging.basicConfig(level=logging.INFO)
logging.getLogger("uvicorn.access").addFilter(_NoiseFilter())
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MOCK = os.getenv("NURSEARM_MOCK", "0") == "1"
# Use the real Google Calendar even while the robot is mocked, so the schedule can be
# tested against a live calendar without any hardware attached.
CALENDAR_REAL = os.getenv("NURSEARM_CALENDAR_REAL", "0") == "1"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WEB_DIR = Path(__file__).resolve().parent / "web"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
CAMERA2_INDEX = int(os.getenv("NURSEARM_CAMERA2_INDEX", "2"))

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
        # Serializes UI/handover/scheduled movements through this process so the
        # medication scheduler never stacks a rollout on top of a live one.
        self._robot_lock = asyncio.Lock()
        self.calendar = build_client(
            mock=MOCK and not CALENDAR_REAL,
            calendar_id=calendar_config().get("calendar_id", "primary"),
        )
        self.scheduler = PillScheduler(
            calendar=self.calendar,
            config=calendar_config(),
            runner=self._run_scheduled_skill,
            robot_busy=lambda: self._robot_lock.locked(),
            state_path=DATA_DIR / "calendar_state.json",
            audit=self.audit,
        )
        self.agent: OllamaMCPAgent | ClaudeMCPAgent | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._ws_clients: set[WebSocket] = set()
        self._latest_scene: SceneObservation | None = None
        self._latest_jpg: bytes = self._encode_jpg(_BLANK_FRAME)
        self._latest_palm_jpg: bytes = self._encode_jpg(_BLANK_FRAME)
        self._latest_cam2_jpg: bytes = self._encode_jpg(_BLANK_FRAME)
        self._latest_palm_result: dict = {"detected": False}
        self._latest_robot_state: dict = {}
        self._palm_log_tick: int = 0
        self._camera_task: asyncio.Task | None = None
        self._cam2_task: asyncio.Task | None = None
        self._robot_task: asyncio.Task | None = None
        self._cam2_capture: cv2.VideoCapture | None = None
        self._cam2_lock = threading.Lock()  # guards cam2 VideoCapture from concurrent release
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
        self._cam2_task = asyncio.create_task(self._camera2_loop())
        self._robot_task = asyncio.create_task(self._robot_poll_loop())
        asyncio.create_task(self._preload_whisper())
        self.scheduler.start()
        logger.info("Medication scheduler started (calendar=%s).", self.scheduler.status().get("backend"))

    async def close(self) -> None:
        await self.scheduler.stop()
        if self._camera_task is not None:
            self._camera_task.cancel()
        if self._cam2_task is not None:
            self._cam2_task.cancel()
        if self._robot_task is not None:
            self._robot_task.cancel()
        if self._cam2_capture is not None:
            self._cam2_capture.release()
            self._cam2_capture = None
        if self.agent is not None:
            await self.agent.close()
        await self.mcp.close()
        self.robot.disconnect()
        self.perception.close()

    async def _run_skill_with_cameras(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Release UI camera handles, run an ACT skill, then restore the live streams.

        Serialized by ``self._robot_lock`` so the UI, direct endpoints, and the
        medication scheduler never run two rollouts at once.
        """
        async with self._robot_lock:
            camera_tasks = [t for t in (self._camera_task, self._cam2_task) if t is not None]
            for task in camera_tasks:
                task.cancel()
            if camera_tasks:
                await asyncio.gather(*camera_tasks, return_exceptions=True)
            self._camera_task = None
            self._cam2_task = None
            if self._cam2_capture is not None:
                self._cam2_capture.release()
                self._cam2_capture = None
            self.perception.close()

            try:
                result = await asyncio.to_thread(
                    self.skills.run,
                    name,
                    arguments,
                    self.robot,
                    self.perception,
                )
                return result.summary()
            finally:
                self._camera_task = asyncio.create_task(self._camera_loop())
                self._cam2_task = asyncio.create_task(self._camera2_loop())

    async def run_handover(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run the handover ACT skill with the camera-release dance."""
        return await self._run_skill_with_cameras("handover_pill", arguments)

    async def _run_scheduled_skill(self, skill: str, args: dict[str, Any]) -> dict[str, Any]:
        """Runner the medication scheduler calls when a labelled event becomes due."""
        return await self._run_skill_with_cameras(skill, args)

    # -- calendar event management ----------------------------------------------

    async def create_calendar_event(
        self, trigger_key: str, start_iso: str, daily: bool
    ) -> dict[str, Any]:
        trigger = self.scheduler.triggers.get(trigger_key)
        if trigger is None:
            raise ValueError(f"unknown trigger {trigger_key!r}")
        try:
            start = datetime.fromisoformat(start_iso)
        except ValueError as exc:
            raise ValueError(f"invalid start time {start_iso!r}") from exc
        if start.tzinfo is None:
            start = start.astimezone()  # interpret a bare datetime as local time
        color_id = trigger.color_ids[0] if trigger.color_ids else None
        event = await asyncio.to_thread(
            self.calendar.create_event, trigger.label, start, color_id=color_id, daily=daily
        )
        await self.scheduler.poll()
        return {"ok": True, "id": event.id, "label": trigger.label, "start_iso": event.start.isoformat()}

    async def delete_calendar_event(self, event_id: str) -> dict[str, Any]:
        await asyncio.to_thread(self.calendar.delete_event, event_id)
        self.scheduler.fired.discard(event_id)
        self.scheduler.skipped.discard(event_id)
        await self.scheduler.poll()
        return {"ok": True, "id": event_id}

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
            color = self._make_offline_frame(color)
        raw_jpg = self._encode_jpg(color)
        palm_jpg = self._encode_jpg(self._draw_palm(color, depth))
        return raw_jpg, palm_jpg

    # -- secondary (robot-mounted) camera ----------------------------------------

    async def _camera2_loop(self) -> None:
        """Capture continuously from the robot-mounted camera (HBV HD CAMERA)."""
        def _open() -> cv2.VideoCapture | None:
            cap = cv2.VideoCapture(CAMERA2_INDEX, cv2.CAP_V4L2)
            if not cap.isOpened():
                logger.warning("Camera 2 (index %s) could not be opened.", CAMERA2_INDEX)
                return None
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            for _ in range(10):  # brief warmup for HBV camera
                cap.grab()
            logger.info("Camera 2 opened (index=%s, HBV HD CAMERA).", CAMERA2_INDEX)
            return cap

        self._cam2_capture = await asyncio.to_thread(_open)

        while True:
            try:
                jpg = await asyncio.to_thread(self._capture_cam2_jpg)
                self._latest_cam2_jpg = jpg
            except Exception as exc:
                logger.debug("camera2 capture error: %s", exc)
            await asyncio.sleep(1 / 30)

    async def _robot_poll_loop(self) -> None:
        """Read motor positions at ~10 Hz and cache them for the /robot/state endpoint."""
        while True:
            try:
                positions = await asyncio.to_thread(self.robot.get_state)
                self._latest_robot_state = positions
            except Exception as exc:
                logger.debug("robot poll error: %s", exc)
            await asyncio.sleep(0.1)  # 10 Hz

    def _capture_cam2_jpg(self) -> bytes:
        with self._cam2_lock:
            if self._cam2_capture is None or not self._cam2_capture.isOpened():
                return self._encode_jpg(_BLANK_FRAME)
            ok, frame = self._cam2_capture.read()
            if not ok or frame is None or frame.size == 0:
                return self._encode_jpg(_BLANK_FRAME)
            return self._encode_jpg(frame)

    def _release_cam2(self) -> None:
        """Release the cam2 VideoCapture under its lock (blocks until any active read finishes)."""
        with self._cam2_lock:
            if self._cam2_capture is not None:
                self._cam2_capture.release()
                self._cam2_capture = None

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

    async def get_whisper(self) -> WhisperModel:
        async with self._whisper_lock:
            if self._whisper is None:
                self._whisper = await asyncio.to_thread(self._load_whisper)
        return self._whisper

    @staticmethod
    def _load_whisper() -> WhisperModel:
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
                segments, _ = model.transcribe(tmp_path, beam_size=5, vad_filter=True)
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
            "robot_connected": self.robot.mock or bool(getattr(self.robot, "_bus", None)),
            "camera_connected": scene.get("ok", False),
            "skills": [
                {"name": info.name, "description": info.description, "kind": info.kind}
                for info in self.skills.info()
            ],
            "scene": scene,
            "audit_count": len(self.audit.read_all()),
        }

    @staticmethod
    def _make_offline_frame(color: np.ndarray) -> np.ndarray:
        frame = color.copy()
        frame[:] = (28, 24, 34)
        cv2.putText(
            frame,
            "No camera connected",
            (155, 235),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (234, 235, 240),
            2,
        )
        return frame


state: AppState | None = None
_ngrok_url: str | None = None
_openclaw_last_seen: float | None = None
_OPENCLAW_ACTIVE_WINDOW_S = 8


def _openclaw_status() -> dict[str, Any]:
    if _openclaw_last_seen is None:
        return {"active": False, "last_seen_seconds_ago": None}
    age = max(0.0, time.monotonic() - _openclaw_last_seen)
    return {
        "active": age <= _OPENCLAW_ACTIVE_WINDOW_S,
        "last_seen_seconds_ago": round(age, 1),
    }


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
    try:
        subprocess.Popen(  # noqa: S603
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.warning(
            "Ollama is not installed; continuing without a local agent. Install it from "
            "https://ollama.com or set AGENT_BACKEND=claude. Chat will be unavailable until then."
        )
        return
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


@app.get("/console")
async def console_page() -> FileResponse:
    return FileResponse(WEB_DIR / "console.html")


@app.get("/business")
async def business_page() -> FileResponse:
    return FileResponse(WEB_DIR / "business.html")


@app.get("/landing")
async def landing_page() -> FileResponse:
    return FileResponse(WEB_DIR / "landing.html")


@app.get("/static/{path:path}")
async def static_file(path: str) -> FileResponse:
    return FileResponse(WEB_DIR / path)


@app.get("/health")
async def health() -> dict[str, Any]:
    ollama = await state.agent.model_status() if state.agent else {"available": False}
    return {
        "ok": True,
        "mock": MOCK,
        "ollama": ollama,
        "ngrok_url": _ngrok_url,
        "openclaw": _openclaw_status(),
    }


@app.post("/integrations/openclaw/heartbeat")
async def openclaw_heartbeat() -> dict[str, bool]:
    global _openclaw_last_seen
    _openclaw_last_seen = time.monotonic()
    return {"ok": True}


@app.get("/qr.svg")
async def qr_svg() -> Response:
    """SVG QR code for the active ngrok tunnel URL."""
    if not _ngrok_url:
        raise HTTPException(status_code=404, detail="No remote tunnel active")
    import io

    import segno
    qr = segno.make_qr(_ngrok_url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=5, border=2, dark="#c1272d", light="#fff9f1")
    return Response(
        content=buf.getvalue(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )


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


@app.get("/stream/2")
async def stream2_view() -> StreamingResponse:
    """MJPEG stream from the robot-mounted HBV HD CAMERA (camera 2)."""
    async def generate():
        while True:
            jpg = state._latest_cam2_jpg
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
async def transcribe(audio: Annotated[UploadFile, File()]) -> dict[str, str]:
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
    logger.info("Chat request started: %s", msg.text)
    try:
        reply = await state.agent.handle(msg.text)
    except (OllamaUnavailableError, ClaudeUnavailableError) as exc:
        logger.error("Chat request failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        logger.exception("Chat request failed unexpectedly")
        raise
    logger.info("Chat request completed")
    return {"reply": reply}


class HandoverRequest(BaseModel):
    color: Literal["green", "black"]
    duration_s: float | None = None


@app.post("/skills/handover-pill")
async def run_handover_pill(request: HandoverRequest) -> dict[str, Any]:
    """Run the handover ACT skill directly, without asking the LLM to select a tool."""
    arguments: dict[str, Any] = {"color": request.color}
    if request.duration_s is not None:
        arguments["duration_s"] = request.duration_s
    logger.info("Direct handover started: color=%s", request.color)
    try:
        result = await state.run_handover(arguments)
    except Exception as exc:
        logger.exception("Direct handover failed: color=%s", request.color)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    logger.info("Direct handover completed: color=%s", request.color)
    return result


# -- calendar / medication schedule ---------------------------------------------


@app.get("/calendar/status")
async def calendar_status() -> dict[str, Any]:
    """Connection + Auto-pilot state for the schedule panel header."""
    return state.scheduler.status()


@app.get("/calendar/schedule")
async def calendar_schedule() -> dict[str, Any]:
    """Upcoming pill events, their status, and the current due/pending firing."""
    payload = state.scheduler.schedule_payload()
    payload["triggers"] = state.scheduler.trigger_options()
    return payload


class AutoPilotIn(BaseModel):
    enabled: bool


@app.post("/calendar/auto-pilot")
async def calendar_auto_pilot(body: AutoPilotIn) -> dict[str, Any]:
    state.scheduler.set_auto_pilot(body.enabled)
    return {"ok": True, "auto_pilot": body.enabled}


class NewEventIn(BaseModel):
    trigger: str            # green | black | sort (a key from calendar.yaml)
    start_iso: str          # ISO datetime; bare datetimes are treated as local time
    daily: bool = False


@app.post("/calendar/events")
async def calendar_create_event(body: NewEventIn) -> dict[str, Any]:
    try:
        return await state.create_calendar_event(body.trigger, body.start_iso, body.daily)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CalendarUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/calendar/events/{event_id}")
async def calendar_delete_event(event_id: str) -> dict[str, Any]:
    try:
        return await state.delete_calendar_event(event_id)
    except CalendarUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/calendar/fire/{event_id}")
async def calendar_fire_event(event_id: str) -> dict[str, Any]:
    """Run a scheduled pill now, skipping the countdown (the banner's "Run now")."""
    return await state.scheduler.fire_now(event_id)


@app.post("/calendar/skip/{event_id}")
async def calendar_skip_event(event_id: str) -> dict[str, Any]:
    """Dismiss a due/pending pill so it never fires (the banner's "Skip")."""
    return state.scheduler.skip(event_id)


# -- SmolVLA sort skill ---------------------------------------------------------


class SortSmolVLARequest(BaseModel):
    duration_s: float | None = None
    task: str | None = None


@app.post("/skills/sort-smolvla")
async def run_sort_smolvla(request: SortSmolVLARequest) -> dict[str, Any]:
    """Run the SmolVLA pill-sorting skill directly, without asking the LLM."""
    arguments: dict[str, Any] = {}
    if request.duration_s is not None:
        arguments["duration_s"] = request.duration_s
    if request.task is not None:
        arguments["task"] = request.task
    logger.info("SmolVLA sort started")
    try:
        result = await state._run_skill_with_cameras("sort_pills_smolvla", arguments)
    except Exception as exc:
        logger.exception("SmolVLA sort failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    logger.info("SmolVLA sort completed")
    return result


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


@app.get("/robot/state")
async def robot_state_view() -> dict[str, Any]:
    """Current motor positions (normalized). Polled by the UI motor graph."""
    return {"ok": True, "positions": state._latest_robot_state}


class RobotAction(BaseModel):
    action: str           # "home" | "grip" | "release" | "jog" | "move"
    joint: str | None = None
    delta: float | None = None
    direction: str | None = None
    step_m: float = 0.02


@app.post("/robot/action")
async def robot_action(cmd: RobotAction) -> dict[str, Any]:
    """Execute a primitive robot movement."""
    try:
        if cmd.action == "home":
            await asyncio.to_thread(state.robot.home)
        elif cmd.action == "grip":
            await asyncio.to_thread(state.robot.grip)
        elif cmd.action == "release":
            await asyncio.to_thread(state.robot.release)
        elif cmd.action == "jog":
            if cmd.joint is None or cmd.delta is None:
                raise HTTPException(status_code=400, detail="jog requires 'joint' and 'delta'")
            await asyncio.to_thread(state.robot.jog, cmd.joint, cmd.delta)
        elif cmd.action == "move":
            if cmd.direction is None:
                raise HTTPException(status_code=400, detail="move requires 'direction'")
            await asyncio.to_thread(state.robot.move_direction, cmd.direction, cmd.step_m)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {cmd.action!r}")
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "action": cmd.action}


def main() -> None:
    import uvicorn

    uvicorn.run("nursearm.interface.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
