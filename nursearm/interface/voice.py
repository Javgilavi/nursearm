"""Voice I/O. STT (speech in) and TTS (speech out).

Strategy (see README §Tech stack):
  - STT hot path: Deepgram Nova-3 streaming (sub-300ms). Whisper offline fallback.
  - Zero-key safety net: the browser Web Speech API in the web UI (no server needed).
  - TTS: ElevenLabs / Cartesia for natural speech; pyttsx3 as an offline fallback.

The judge calls ``say()`` via its speak tool. ``transcribe()`` is used by the optional
voice endpoint / mic streaming.
"""

from __future__ import annotations

import logging

from nursearm import config

logger = logging.getLogger(__name__)


def say(text: str) -> None:
    """Speak `text` aloud. Falls back to a log line if no TTS backend is configured."""
    api_key = config.env("ELEVENLABS_API_KEY")
    if not api_key:
        logger.info("TTS (no backend): %s", text)
        return
    # TODO: stream `text` to ElevenLabs/Cartesia and play the audio.
    logger.info("TTS: %s", text)


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe a chunk of audio to text (Deepgram hot path, Whisper fallback)."""
    # TODO: send to Deepgram Nova-3; on failure, fall back to local Whisper.
    raise NotImplementedError("wire Deepgram/Whisper; browser Web Speech API works key-free in the UI")
