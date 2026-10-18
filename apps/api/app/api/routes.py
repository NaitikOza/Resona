from __future__ import annotations

import asyncio
import json
import io
import logging
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.config import settings
from app.dependencies import (
    get_database,
    get_diarizer,
    get_pipeline,
    get_report_service,
    get_transcriber,
)
from app.models.schemas import (
    ApiResponse,
    ClinicalEvent,
    ClinicalEventCreate,
    EventPatch,
    ReportRecord,
    ReviewItem,
    ReviewItemPatch,
    SessionCreate,
    SessionRecord,
    SessionStatus,
    TranscriptPatch,
    TranscriptSegment,
    TranscriptSegmentCreate,
)
from app.services.reconciliation import EventReconciler
from app.services.scenarios import list_scenarios, load_scenario
from app.services.diarization import DiarizationUnavailable, SpeakerTurn, assign_speakers
from app.services.transcription import PcmWindow, TranscriptionUnavailable


router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)
_speaker_jobs: dict[str, dict[str, object]] = {}
_speaker_tasks: dict[str, asyncio.Task[None]] = {}


def ok(data: object) -> dict[str, object]:
    return {"success": True, "data": data}


def not_found(error: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(error).strip("'"))


@router.get("/health")
def health() -> dict[str, object]:
    model = get_transcriber().status()
    diarization = get_diarizer().status()
    return ok(
        {
            "status": "ok",
            "scope": "documentation",
            "asr": model.model_dump(mode="json"),
            "speaker_detection": diarization.model_dump(mode="json"),
            "rules_engine": "ready",
        }
    )


@router.get("/scenarios")
def scenarios() -> dict[str, object]:
    return ok(list_scenarios())


@router.get("/sessions")
def sessions() -> dict[str, object]:
    return ok(get_database().list_sessions())


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate) -> dict[str, object]:
    try:
        return ok(get_database().create_session(payload))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, object]:
    try:
        return ok(get_database().get_session(session_id))
    except KeyError as error:
        raise not_found(error) from error


def _transition(session_id: str, target: SessionStatus) -> dict[str, object]:
    try:
        return ok(get_database().transition_session(session_id, target))
    except KeyError as error:
        raise not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/start")
def start_session(session_id: str) -> dict[str, object]:
    return _transition(session_id, SessionStatus.RECORDING)


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str) -> dict[str, object]:
    return _transition(session_id, SessionStatus.PAUSED)


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str) -> dict[str, object]:
    return _transition(session_id, SessionStatus.RECORDING)


@router.post("/sessions/{session_id}/finish")
async def finish_session(session_id: str) -> dict[str, object]:
    result = _transition(session_id, SessionStatus.READY_FOR_REVIEW)
    EventReconciler(get_database()).rebuild_open_items(session_id)
    _start_speaker_job(session_id)
    return result


@router.get("/sessions/{session_id}/speakers/status")
def speaker_detection_status(session_id: str) -> dict[str, object]:
    try:
        get_database().get_session(session_id)
    except KeyError as error:
        raise not_found(error) from error
    return ok(
        _speaker_jobs.get(
            session_id,
            {"status": "SKIPPED", "speaker_count": 0},
        )
    )


@router.post("/sessions/{session_id}/speakers")
async def detect_session_speakers(session_id: str) -> dict[str, object]:
    try:
        get_database().get_session(session_id)
        detected = await _detect_session_speakers(session_id, required=True)
        return ok(
            {
                "segments": get_database().list_segments(session_id),
                "speaker_count": len(set(detected.values())),
            }
        )
    except KeyError as error:
        raise not_found(error) from error
    except DiarizationUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, object]:
    deleted = get_database().delete_session(session_id)
    session_path = settings.storage_path / session_id
    if session_path.is_dir():
        shutil.rmtree(session_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return ok({"deleted": True, "session_id": session_id})


@router.post("/sessions/{session_id}/transcript", status_code=201)
def add_transcript_segment(
    session_id: str, payload: TranscriptSegmentCreate
) -> dict[str, object]:
    try:
        segment, events = get_pipeline().ingest(session_id, payload)
        return ok({"segment": segment, "events": events})
    except KeyError as error:
        raise not_found(error) from error


@router.get("/sessions/{session_id}/transcript")
def transcript(session_id: str) -> dict[str, object]:
    try:
        get_database().get_session(session_id)
        return ok(get_database().list_segments(session_id))
    except KeyError as error:
        raise not_found(error) from error


@router.patch("/transcript/{segment_id}")
def patch_transcript(segment_id: str, payload: TranscriptPatch) -> dict[str, object]:
    try:
        return ok(get_database().patch_segment(segment_id, payload))
    except KeyError as error:
        raise not_found(error) from error


@router.get("/sessions/{session_id}/events")
def events(session_id: str) -> dict[str, object]:
    try:
        get_database().get_session(session_id)
        return ok(get_database().list_events(session_id))
    except KeyError as error:
        raise not_found(error) from error


@router.get("/sessions/{session_id}/audio/{segment_id}", response_model=None)
def segment_audio(session_id: str, segment_id: str) -> Response:
    try:
        segment = get_database().get_segment(segment_id)
        if segment.session_id != session_id:
            raise KeyError("Transcript segment not found in this session")
        source_value = get_database().get_audio_path(session_id)
        source = Path(source_value) if source_value else settings.storage_path / session_id / "uploaded.wav"
        if not source.is_file():
            raise HTTPException(
                status_code=404,
                detail="Source audio was not retained for this segment",
            )
        start_frame = segment.start_ms * 16
        frame_count = max(1, (segment.end_ms - segment.start_ms) * 16)
        if source.suffix.lower() == ".wav":
            with wave.open(str(source), "rb") as audio:
                audio.setpos(min(start_frame, audio.getnframes()))
                pcm = audio.readframes(frame_count)
        else:
            with source.open("rb") as audio:
                audio.seek(start_frame * 2)
                pcm = audio.read(frame_count * 2)
        output = io.BytesIO()
        with wave.open(output, "wb") as clip:
            clip.setnchannels(1)
            clip.setsampwidth(2)
            clip.setframerate(16_000)
            clip.writeframes(pcm)
        return Response(
            output.getvalue(),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )
    except KeyError as error:
        raise not_found(error) from error


@router.post("/sessions/{session_id}/events", status_code=201)
def add_manual_event(session_id: str, payload: ClinicalEventCreate) -> dict[str, object]:
    try:
        event = get_database().add_event(session_id, payload, origin="reviewer")
        return ok(event)
    except KeyError as error:
        raise not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/events/{event_id}")
def patch_event(event_id: str, payload: EventPatch) -> dict[str, object]:
    try:
        event = get_database().patch_event(event_id, payload)
        EventReconciler(get_database()).rebuild_open_items(event.session_id)
        return ok(event)
    except KeyError as error:
        raise not_found(error) from error


@router.get("/sessions/{session_id}/review-items")
def review_items(session_id: str) -> dict[str, object]:
    try:
        get_database().get_session(session_id)
        return ok(get_database().list_review_items(session_id))
    except KeyError as error:
        raise not_found(error) from error


@router.patch("/review-items/{item_id}")
def patch_review_item(item_id: str, payload: ReviewItemPatch) -> dict[str, object]:
    try:
        return ok(get_database().patch_review_item(item_id, payload))
    except KeyError as error:
        raise not_found(error) from error


@router.post("/sessions/{session_id}/sample/{slug}")
def play_sample(session_id: str, slug: str) -> dict[str, object]:
    try:
        scenario = load_scenario(slug)
        session = get_database().get_session(session_id)
        if session.status == SessionStatus.CREATED:
            get_database().transition_session(session_id, SessionStatus.PROCESSING)
        elif session.status not in {SessionStatus.PROCESSING, SessionStatus.ERROR}:
            raise ValueError("Sample data can only be loaded into a new sample session")
        ingested: list[dict[str, object]] = []
        for raw in scenario["segments"]:
            segment, extracted_events = get_pipeline().ingest(
                session_id,
                TranscriptSegmentCreate(
                    start_ms=raw["start_ms"],
                    end_ms=raw["end_ms"],
                    raw_text=raw["text"],
                    speaker_label=raw.get("speaker", "Unknown"),
                    asr_engine="curated-simulation-transcript",
                    confidence=raw.get("confidence", 1.0),
                ),
            )
            ingested.append({"segment": segment, "events": extracted_events})
        final = get_database().transition_session(
            session_id,
            SessionStatus.READY_FOR_REVIEW,
            duration_ms=max(item["end_ms"] for item in scenario["segments"]),
        )
        return ok({"session": final, "ingested": ingested, "scenario": scenario["title"]})
    except KeyError as error:
        raise not_found(error) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/sessions/{session_id}/audio/upload")
async def upload_audio(
    session_id: str, file: Annotated[UploadFile, File(description="Mono PCM16 16 kHz WAV")]
) -> dict[str, object]:
    try:
        session = get_database().get_session(session_id)
        if session.status not in {SessionStatus.CREATED, SessionStatus.ERROR}:
            raise ValueError("Audio can only be uploaded to a new or failed upload session")
        get_database().transition_session(session_id, SessionStatus.PROCESSING)
        suffix = Path(file.filename or "practice.wav").suffix.lower()
        if suffix != ".wav":
            raise ValueError("Upload a mono 16 kHz, 16-bit PCM WAV file")
        session_dir = settings.storage_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        retained_path = session_dir / "uploaded.wav"
        if settings.keep_audio:
            target = retained_path
            with target.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    destination.write(chunk)
        else:
            temporary = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            target = Path(temporary.name)
            try:
                while chunk := await file.read(1024 * 1024):
                    temporary.write(chunk)
            finally:
                temporary.close()
        speaker_turns: list[SpeakerTurn] = []
        if get_diarizer().status().available:
            try:
                speaker_turns = await get_diarizer().diarize(target)
            except Exception:
                speaker_turns = []
        segments = await get_transcriber().transcribe_wav(target)
        ingested = [get_pipeline().ingest(session_id, segment) for segment in segments]
        if speaker_turns:
            _save_speaker_turns(session_id, speaker_turns)
        duration = max((segment.end_ms for segment, _ in ingested), default=0)
        final = get_database().transition_session(
            session_id, SessionStatus.READY_FOR_REVIEW, duration_ms=duration
        )
        if not settings.keep_audio:
            target.unlink(missing_ok=True)
        return ok(
            {
                "session": final,
                "segments": [segment for segment, _ in ingested],
                "event_count": sum(len(events) for _, events in ingested),
                "audio_retained": settings.keep_audio,
            }
        )
    except KeyError as error:
        raise not_found(error) from error
    except TranscriptionUnavailable as error:
        get_database().transition_session(session_id, SessionStatus.ERROR)
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        try:
            get_database().transition_session(session_id, SessionStatus.ERROR)
        except (ValueError, KeyError):
            pass
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/sessions/{session_id}/audio/addendum", status_code=201)
async def add_voice_addendum(
    session_id: str, file: Annotated[UploadFile, File(description="Recorded addendum")]
) -> dict[str, object]:
    target: Path | None = None
    try:
        session = get_database().get_session(session_id)
        if session.status not in {
            SessionStatus.READY_FOR_REVIEW,
            SessionStatus.COMPLETED,
        }:
            raise ValueError("Finish the main recording before adding a voice note")
        suffix = Path(file.filename or "addendum.wav").suffix.lower()
        if suffix != ".wav":
            raise ValueError("The voice note must be a WAV recording")
        temporary = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        target = Path(temporary.name)
        try:
            while chunk := await file.read(1024 * 1024):
                temporary.write(chunk)
        finally:
            temporary.close()

        offset_ms = session.duration_ms + 1_000
        transcribed = await get_transcriber().transcribe_wav(target, offset_ms=offset_ms)
        if not transcribed:
            raise ValueError("No speech was detected. Try the voice note again.")
        ingested = [
            get_pipeline().ingest(
                session_id,
                segment.model_copy(
                    update={"asr_engine": f"{segment.asr_engine}/voice-addendum"}
                ),
            )
            for segment in transcribed
        ]
        saved_segments = [segment for segment, _ in ingested]
        role_labels = assign_speakers(saved_segments, [])
        if role_labels:
            get_database().update_speaker_labels(session_id, role_labels)
            saved_segments = [
                get_database().get_segment(segment.id) for segment in saved_segments
            ]
        EventReconciler(get_database()).rebuild_open_items(session_id)
        return ok(
            {
                "session": get_database().get_session(session_id),
                "segments": saved_segments,
                "events": [event for _, events in ingested for event in events],
            }
        )
    except KeyError as error:
        raise not_found(error) from error
    except TranscriptionUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        if target is not None:
            target.unlink(missing_ok=True)


@router.post("/sessions/{session_id}/reports", status_code=201)
def generate_report(session_id: str) -> dict[str, object]:
    try:
        report = get_report_service().generate(session_id)
        session = get_database().get_session(session_id)
        if session.status == SessionStatus.READY_FOR_REVIEW:
            get_database().transition_session(session_id, SessionStatus.COMPLETED)
        return ok(report)
    except KeyError as error:
        raise not_found(error) from error


@router.get("/sessions/{session_id}/reports/latest")
def latest_report(session_id: str) -> dict[str, object]:
    try:
        return ok(get_database().get_latest_report(session_id))
    except KeyError as error:
        raise not_found(error) from error


@router.get("/sessions/{session_id}/export", response_model=None)
def export_report(
    session_id: str, format: Literal["json", "csv", "html"] = "json"
) -> PlainTextResponse | HTMLResponse:
    try:
        report = get_database().get_latest_report(session_id)
    except KeyError:
        try:
            report = get_report_service().generate(session_id)
        except KeyError as error:
            raise not_found(error) from error
    filename = f"resona-{session_id[:8]}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "html":
        return HTMLResponse(get_report_service().html(report), headers=headers)
    if format == "csv":
        return PlainTextResponse(
            get_report_service().csv(report), media_type="text/csv", headers=headers
        )
    return PlainTextResponse(
        json.dumps(report.structured_json, indent=2),
        media_type="application/json",
        headers=headers,
    )


async def _detect_session_speakers(
    session_id: str, *, required: bool = False
) -> dict[str, str]:
    database = get_database()
    source_value = database.get_audio_path(session_id)
    if not source_value or not Path(source_value).is_file():
        if required:
            raise DiarizationUnavailable("No retained recording is available.")
        return {}
    if not get_diarizer().status().available:
        if required:
            raise DiarizationUnavailable(get_diarizer().status().detail)
        return {}
    try:
        turns = await get_diarizer().diarize(Path(source_value))
    except Exception as error:
        if required:
            raise DiarizationUnavailable(f"Speaker detection failed: {error}") from error
        return {}
    return _save_speaker_turns(session_id, turns)


def _start_speaker_job(session_id: str) -> None:
    existing = _speaker_tasks.get(session_id)
    if existing is not None and not existing.done():
        return
    _speaker_jobs[session_id] = {"status": "PROCESSING", "speaker_count": 0}
    task = asyncio.create_task(_run_speaker_job(session_id))
    _speaker_tasks[session_id] = task


async def _run_speaker_job(session_id: str) -> None:
    try:
        try:
            await _refine_session_transcript(session_id)
        except Exception:
            logger.exception("Final transcript pass failed for %s", session_id)
        detected = await _detect_session_speakers(session_id, required=True)
        _speaker_jobs[session_id] = {
            "status": "READY",
            "speaker_count": len(set(detected.values())),
        }
    except DiarizationUnavailable as error:
        logger.warning("Speaker detection skipped for %s: %s", session_id, error)
        _speaker_jobs[session_id] = {"status": "SKIPPED", "speaker_count": 0}
    except Exception:
        logger.exception("Speaker detection failed for %s", session_id)
        _speaker_jobs[session_id] = {"status": "FAILED", "speaker_count": 0}


async def _refine_session_transcript(session_id: str) -> None:
    """Replace short-window live results with one full-context Whisper pass."""
    database = get_database()
    source_value = database.get_audio_path(session_id)
    if not source_value:
        return
    source = Path(source_value)
    if source.suffix.lower() != ".pcm" or not source.is_file():
        return
    pcm = source.read_bytes()
    if len(pcm) < 3_200:
        return
    duration_ms = len(pcm) * 1000 // (16_000 * 2)
    refined = await get_transcriber().transcribe_pcm(
        PcmWindow(pcm16=pcm, start_ms=0, end_ms=duration_ms)
    )
    if not refined:
        return
    database.clear_generated_transcript(session_id)
    for segment in refined:
        get_pipeline().ingest(session_id, segment)


def _save_speaker_turns(
    session_id: str, turns: list[SpeakerTurn]
) -> dict[str, str]:
    database = get_database()
    assignments = assign_speakers(database.list_segments(session_id), turns)
    database.update_speaker_labels(session_id, assignments)
    return assignments

