from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.routes as routes
from app.dependencies import get_database
from app.models.schemas import TranscriptSegmentCreate


def create_session(client: TestClient, mode: str = "SAMPLE_SCENARIO") -> dict:
    response = client.post(
        "/api/sessions",
        json={
            "case_label": "Demo Case",
            "mode": mode,
            "consent_recorded": True,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_health_reports_local_model_state(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["scope"] == "documentation"
    assert payload["data"]["asr"]["available"] is False
    assert payload["data"]["speaker_detection"]["engine"] == "pyannote.audio"
    assert payload["data"]["speaker_detection"]["available"] is False


def test_session_does_not_require_a_separate_consent_field(client: TestClient) -> None:
    response = client.post(
        "/api/sessions",
        json={
            "case_label": "Trauma Case",
            "mode": "LIVE_MICROPHONE",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["consent_recorded"] is False


def test_sessions_are_available_for_the_patient_library(client: TestClient) -> None:
    created = create_session(client)
    response = client.get("/api/sessions")

    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == created["id"]


def test_sample_to_report_and_exports(client: TestClient) -> None:
    session = create_session(client)
    loaded = client.post(f"/api/sessions/{session['id']}/sample/02-blood-request-only")
    assert loaded.status_code == 200

    events = client.get(f"/api/sessions/{session['id']}/events").json()["data"]
    assert events
    assert not any(event["state"] == "COMPLETED" for event in events)
    assert events[0]["source_segment_ids"]

    generated = client.post(f"/api/sessions/{session['id']}/reports")
    assert generated.status_code == 201
    report = generated.json()["data"]
    assert report["structured_json"]["title"] == "Resona — Emergency Documentation Report"
    assert "blood request" in report["structured_json"]["handoff_summary"].lower()
    assert "emergency_overview" not in report["structured_json"]
    assert "state" not in report["structured_json"]["timeline"][0]
    assert report["structured_json"]["timeline"][0]["speaker"]
    completed = client.get(f"/api/sessions/{session['id']}").json()["data"]
    assert completed["status"] == "COMPLETED"

    for export_format, content_type in (
        ("json", "application/json"),
        ("csv", "text/csv"),
        ("html", "text/html"),
    ):
        exported = client.get(
            f"/api/sessions/{session['id']}/export?format={export_format}"
        )
        assert exported.status_code == 200
        assert content_type in exported.headers["content-type"]
        if export_format == "html":
            assert "Timeline map" in exported.text
            assert "Handoff summary" in exported.text
            assert "Emergency record check" not in exported.text


def test_reviewer_edit_creates_audit_and_changes_report(client: TestClient) -> None:
    session = create_session(client)
    client.post(f"/api/sessions/{session['id']}/sample/01-closed-loop-iv")
    events = client.get(f"/api/sessions/{session['id']}/events").json()["data"]
    event = events[0]
    updated = client.patch(
        f"/api/events/{event['id']}",
        json={
            "description": "IV access request verified by reviewer.",
            "reviewer_status": "EDITED",
            "change_reason": "Verified against simulated source",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["reviewer_status"] == "EDITED"
    report = client.post(f"/api/sessions/{session['id']}/reports").json()["data"]
    assert report["structured_json"]["reviewer_edits"]


def test_diarization_does_not_overwrite_a_reviewer_speaker_label(client: TestClient) -> None:
    session = create_session(client)
    client.post(f"/api/sessions/{session['id']}/sample/01-closed-loop-iv")
    transcript = client.get(f"/api/sessions/{session['id']}/transcript").json()["data"]
    segment = transcript[0]
    client.patch(
        f"/api/transcript/{segment['id']}",
        json={"speaker_label": "Charge Nurse", "review_status": "CORRECTED"},
    )

    updated = get_database().update_speaker_labels(
        session["id"], {segment["id"]: "Speaker 1"}
    )

    assert updated[0].speaker_label == "Charge Nurse"


def test_voice_addendum_is_transcribed_and_added_before_report(
    client: TestClient, monkeypatch
) -> None:
    class AddendumTranscriber:
        async def transcribe_wav(self, _path, offset_ms: int = 0):
            return [
                TranscriptSegmentCreate(
                    start_ms=offset_ms,
                    end_ms=offset_ms + 1_500,
                    raw_text="Nurse, BP is 110 over 70.",
                    asr_engine="whisper.cpp/test",
                )
            ]

    monkeypatch.setattr(routes, "get_transcriber", lambda: AddendumTranscriber())
    session = create_session(client)
    client.post(f"/api/sessions/{session['id']}/sample/02-blood-request-only")

    response = client.post(
        f"/api/sessions/{session['id']}/audio/addendum",
        files={"file": ("voice-addendum.wav", b"voice", "audio/wav")},
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["segments"][0]["speaker_label"] == "Nurse"
    assert payload["segments"][0]["asr_engine"].endswith("/voice-addendum")
    assert payload["events"][0]["category"] == "MEASUREMENT"


def test_finish_returns_before_speaker_detection_completes(
    client: TestClient, monkeypatch
) -> None:
    async def delayed_detection(*_args, **_kwargs) -> dict[str, str]:
        await asyncio.sleep(0.2)
        return {"segment": "Speaker 1"}

    monkeypatch.setattr(routes, "_detect_session_speakers", delayed_detection)
    session = create_session(client, mode="LIVE_MICROPHONE")
    client.post(f"/api/sessions/{session['id']}/start")

    started = time.perf_counter()
    response = client.post(f"/api/sessions/{session['id']}/finish")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert elapsed < 0.15
    assert response.json()["data"]["status"] == "READY_FOR_REVIEW"
    assert client.get(
        f"/api/sessions/{session['id']}/speakers/status"
    ).json()["data"]["status"] == "PROCESSING"

    time.sleep(0.25)
    completed = client.get(f"/api/sessions/{session['id']}/speakers/status")
    assert completed.json()["data"] == {"status": "READY", "speaker_count": 1}


def test_delete_removes_database_rows_and_session_files(client: TestClient) -> None:
    session = create_session(client)
    session_dir = routes.settings.storage_path / session["id"]
    session_dir.mkdir(parents=True)
    (session_dir / "capture.pcm").write_bytes(b"simulation")
    deleted = client.delete(f"/api/sessions/{session['id']}")
    assert deleted.status_code == 200
    assert not session_dir.exists()
    assert client.get(f"/api/sessions/{session['id']}").status_code == 404


def test_upload_fails_truthfully_when_whisper_is_unavailable(client: TestClient) -> None:
    session = create_session(client, mode="AUDIO_UPLOAD")
    # Minimal RIFF signature is sufficient to reach the feature-availability guard first.
    response = client.post(
        f"/api/sessions/{session['id']}/audio/upload",
        files={"file": ("practice.wav", b"RIFF-not-a-real-wave", "audio/wav")},
    )
    assert response.status_code == 503
    assert "whisper" in response.json()["error"].lower()

