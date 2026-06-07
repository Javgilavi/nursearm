#!/usr/bin/env python3
"""Report that the OpenClaw container is alive to the NurseArm server."""

import asyncio
import os

import httpx

NURSEARM_URL = os.getenv("NURSEARM_URL", "http://host.docker.internal:8000").rstrip("/")
HEARTBEAT_INTERVAL_S = 3


async def main() -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            try:
                await client.post(f"{NURSEARM_URL}/integrations/openclaw/heartbeat")
            except httpx.HTTPError:
                pass
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)


if __name__ == "__main__":
    asyncio.run(main())
