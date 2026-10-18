#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import struct
import sys
import wave
from pathlib import Path

import httpx
import websockets


API = "http://127.0.0.1:8000"
WS = "ws://127.0.0.1:8000"
HEADER = struct.Struct("<III")


async def validate(wav_path: Path) -> None:
    with wave.open(str(wav_path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16_000):
            raise SystemExit("Expected mono 16 kHz PCM16 WAV")
        pcm_frames: list[bytes] = []
        while chunk := source.readframes(4096):
            pcm_frames.append(chunk)

    async with httpx.AsyncClient(timeout=180) as client:
        created = (
            await client.post(
                f"{API}/api/sessions",
                json={
                    "case_label": "Synthetic WebSocket Validation",
                    "mode": "LIVE_MICROPHONE",
                    "consent_recorded": True,
                },
            )
        ).json()["data"]
        session_id = created["id"]
        await client.post(f"{API}/api/sessions/{session_id}/start")

        messages: list[dict[str, object]] = []
        sample_count = 0
        try:
            async with websockets.connect(f"{WS}/ws/sessions/{session_id}/audio") as socket:
                async def receive_until_drained() -> None:
                    while True:
                        payload = json.loads(await socket.recv())
                        messages.append(payload)
                        if (
                            payload.get("type") == "session_state"
                            and payload.get("data", {}).get("status") == "AUDIO_DRAINED"
                        ):
                            return

                reader = asyncio.create_task(receive_until_drained())
                for sequence, pcm in enumerate(pcm_frames):
                    start_ms = round(sample_count / 16_000 * 1000)
                    sample_count += len(pcm) // 2
                    end_ms = round(sample_count / 16_000 * 1000)
                    await socket.send(HEADER.pack(sequence, start_ms, end_ms) + pcm)
                    # Faster than real time, but slow enough to exercise the bounded queue without overflow.
                    await asyncio.sleep(0.075)
                await socket.send(json.dumps({"type": "finish"}))
                await asyncio.wait_for(reader, timeout=180)

            await client.post(f"{API}/api/sessions/{session_id}/finish")
            events = (await client.get(f"{API}/api/sessions/{session_id}/events")).json()["data"]
            segments = (await client.get(f"{API}/api/sessions/{session_id}/transcript")).json()["data"]
            summary = {
                "session_id": session_id,
                "audio_duration_ms": round(sample_count / 16_000 * 1000),
                "websocket_messages": {
                    kind: sum(1 for message in messages if message.get("type") == kind)
                    for kind in sorted({str(message.get("type")) for message in messages})
                },
                "transcript_segments": len(segments),
                "events": [
                    {
                        "state": event["state"],
                        "action": event["normalized_action"],
                        "evidence": event["evidence_text"],
                    }
                    for event in events
                ],
            }
            print(json.dumps(summary, indent=2))
        finally:
            await client.delete(f"{API}/api/sessions/{session_id}")


if __name__ == "__main__":
    target = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1]
        / "local_data/demo/synthetic-trauma-demo.wav"
    )
    asyncio.run(validate(target))
