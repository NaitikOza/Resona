from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.dependencies import get_database, get_pipeline, get_transcriber
from app.models.schemas import SessionStatus
from app.models.schemas import TranscriptSegmentCreate
from app.services.transcription import PcmWindow, TranscriptionUnavailable


router = APIRouter()
HEADER = struct.Struct("<III")
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
# AudioWorklet frames contain 4,096 samples (~256 ms). Keep a bounded minute of
# PCM so a first-run model load cannot exhaust the queue on modest hardware.
MAX_QUEUED_FRAMES = 240
TRAILING_GUARD_MS = 350


def message(kind: str, **data: object) -> dict[str, object]:
    return {"type": kind, "message_id": str(uuid4()), "data": data}


def stable_segments(
    segments: list[TranscriptSegmentCreate],
    *,
    window_start: int,
    window_end: int,
    overlap_ms: int,
    first_window: bool,
    flush: bool,
) -> list[TranscriptSegmentCreate]:
    leading_edge = window_start + overlap_ms
    trailing_edge = window_end - TRAILING_GUARD_MS
    return [
        segment
        for segment in segments
        if (first_window or segment.end_ms > leading_edge)
        and (flush or segment.end_ms < trailing_edge)
    ]


@router.websocket("/ws/sessions/{session_id}/audio")
async def session_audio(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    database = get_database()
    try:
        session = database.get_session(session_id)
    except KeyError:
        await websocket.send_json(message("error", error="Session not found"))
        await websocket.close(code=1008)
        return
    if session.status != SessionStatus.RECORDING:
        await websocket.send_json(
            message("error", error="Session must be recording before audio can stream")
        )
        await websocket.close(code=1008)
        return

    queue: asyncio.Queue[tuple[int, int, int, bytes] | None] = asyncio.Queue(
        maxsize=MAX_QUEUED_FRAMES
    )
    send_lock = asyncio.Lock()
    worker = asyncio.create_task(_audio_worker(websocket, session_id, queue, send_lock))
    await _safe_send(
        websocket,
        send_lock,
        "session_state",
        status="RECORDING",
        sample_rate=SAMPLE_RATE,
        frame_format="12-byte little-endian seq/start_ms/end_ms header + PCM16 mono",
        window_seconds=settings.audio_window_seconds,
    )
    draining = False
    try:
        while True:
            incoming = await websocket.receive()
            if incoming.get("type") == "websocket.disconnect":
                break
            if incoming.get("text") is not None:
                try:
                    control = json.loads(incoming["text"])
                except json.JSONDecodeError:
                    await _safe_send(websocket, send_lock, "warning", warning="Invalid control message ignored")
                    continue
                if control.get("type") == "finish":
                    draining = True
                    await queue.put(None)
                    await worker
                    break
                await _safe_send(websocket, send_lock, "warning", warning="Unknown control message ignored")
                continue
            packet = incoming.get("bytes")
            if packet is None:
                continue
            if len(packet) <= HEADER.size:
                await _safe_send(websocket, send_lock, "warning", warning="Empty audio frame ignored")
                continue
            sequence, start_ms, end_ms = HEADER.unpack_from(packet)
            pcm = packet[HEADER.size :]
            expected_ms = len(pcm) * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE)
            if end_ms <= start_ms or abs((end_ms - start_ms) - expected_ms) > 150:
                await _safe_send(
                    websocket,
                    send_lock,
                    "error",
                    error="Audio frame timestamps do not match its PCM sample count",
                    sequence=sequence,
                )
                continue
            try:
                queue.put_nowait((sequence, start_ms, end_ms, pcm))
            except asyncio.QueueFull:
                await _safe_send(
                    websocket,
                    send_lock,
                    "error",
                    error="Local transcription queue is full; capture stopped without silently dropping audio",
                )
                await websocket.close(code=1013)
                break
            await _safe_send(
                websocket,
                send_lock,
                "ack",
                sequence=sequence,
                queued_frames=queue.qsize(),
            )
    except WebSocketDisconnect:
        pass
    finally:
        if not draining:
            await queue.put(None)
            with suppress(Exception):
                await worker


async def _audio_worker(
    websocket: WebSocket,
    session_id: str,
    queue: asyncio.Queue[tuple[int, int, int, bytes] | None],
    send_lock: asyncio.Lock,
) -> None:
    database = get_database()
    transcriber = get_transcriber()
    pipeline = get_pipeline()
    target_bytes = settings.audio_window_seconds * SAMPLE_RATE * BYTES_PER_SAMPLE
    overlap_bytes = min(1 * SAMPLE_RATE * BYTES_PER_SAMPLE, target_bytes // 2)
    overlap_ms = overlap_bytes * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE)
    buffer = bytearray()
    buffer_start_ms: int | None = None
    buffer_end_ms = 0
    processed_windows = 0
    session_dir = settings.storage_path / session_id
    raw_path = session_dir / "capture.pcm"
    if settings.keep_audio:
        session_dir.mkdir(parents=True, exist_ok=True)

    async def process(flush: bool = False) -> None:
        nonlocal buffer, buffer_start_ms, buffer_end_ms, processed_windows
        if not buffer or buffer_start_ms is None:
            return
        if not flush and len(buffer) < target_bytes:
            return
        window_bytes = bytes(buffer[:target_bytes] if not flush else buffer)
        duration_ms = len(window_bytes) * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE)
        window_start = buffer_start_ms
        window_end = window_start + duration_ms
        if flush:
            buffer = bytearray()
            buffer_start_ms = None
        else:
            consumed_bytes = max(1, len(window_bytes) - overlap_bytes)
            consumed_ms = consumed_bytes * 1000 // (SAMPLE_RATE * BYTES_PER_SAMPLE)
            buffer = buffer[consumed_bytes:]
            buffer_start_ms = window_start + consumed_ms
        await _safe_send(
            websocket,
            send_lock,
            "processing",
            start_ms=window_start,
            end_ms=window_end,
            queued_frames=queue.qsize(),
        )
        try:
            transcribed = await transcriber.transcribe_pcm(
                PcmWindow(window_bytes, window_start, window_end)
            )
            segments = stable_segments(
                transcribed,
                window_start=window_start,
                window_end=window_end,
                overlap_ms=overlap_ms,
                first_window=processed_windows == 0,
                flush=flush,
            )
            processed_windows += 1
            for payload in segments:
                segment, events = pipeline.ingest(session_id, payload)
                await _safe_send(
                    websocket,
                    send_lock,
                    "transcription_final",
                    segment=segment.model_dump(mode="json"),
                )
                for event in events:
                    await _safe_send(
                        websocket,
                        send_lock,
                        "event_added",
                        event=event.model_dump(mode="json"),
                    )
        except TranscriptionUnavailable as error:
            await _safe_send(websocket, send_lock, "error", error=str(error))
        except Exception as error:
            await _safe_send(
                websocket,
                send_lock,
                "error",
                error=f"Local audio window failed: {error}",
                start_ms=window_start,
                end_ms=window_end,
            )

    while True:
        item = await queue.get()
        if item is None:
            await process(flush=True)
            await _safe_send(
                websocket, send_lock, "session_state", status="AUDIO_DRAINED"
            )
            return
        sequence, start_ms, end_ms, pcm = item
        if buffer_start_ms is None:
            buffer_start_ms = start_ms
        buffer_end_ms = max(buffer_end_ms, end_ms)
        buffer.extend(pcm)
        checksum = hashlib.sha256(pcm).hexdigest()
        if settings.keep_audio:
            with raw_path.open("ab") as raw_file:
                raw_file.write(pcm)
        database.add_audio_chunk(
            session_id,
            sequence,
            start_ms,
            end_ms,
            str(raw_path) if settings.keep_audio else None,
            checksum,
            "BUFFERED",
        )
        while len(buffer) >= target_bytes:
            await process()


async def _safe_send(
    websocket: WebSocket, lock: asyncio.Lock, kind: str, **data: object
) -> None:
    async with lock:
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.send_json(message(kind, **data))

