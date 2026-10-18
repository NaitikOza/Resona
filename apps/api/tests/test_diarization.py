from __future__ import annotations

from datetime import UTC, datetime

from app.models.schemas import TranscriptSegment
from app.services.diarization import SpeakerTurn, assign_speakers


def segment(
    segment_id: str, start_ms: int, end_ms: int, text: str
) -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        session_id="session",
        start_ms=start_ms,
        end_ms=end_ms,
        raw_text=text,
        corrected_text=None,
        speaker_label="Unknown",
        asr_engine="test",
        confidence=1,
        review_status="RAW",
        created_at=datetime.now(UTC),
    )


def test_assigns_speakers_by_largest_timestamp_overlap() -> None:
    segments = [
        segment("a", 0, 2_000, "Airway is clear."),
        segment("b", 2_100, 4_000, "Blood pressure is 90 over 60."),
    ]
    turns = [
        SpeakerTurn(0, 1_700, "SPEAKER_04"),
        SpeakerTurn(1_700, 4_000, "SPEAKER_01"),
    ]

    assert assign_speakers(segments, turns) == {
        "a": "Speaker 1",
        "b": "Speaker 2",
    }


def test_uses_explicit_self_identification_for_role_label() -> None:
    segments = [
        segment("a", 0, 2_000, "This is the paramedic giving report."),
        segment("b", 2_100, 4_000, "Blood pressure is 90 over 60."),
    ]
    turns = [SpeakerTurn(0, 4_000, "SPEAKER_00")]

    assert assign_speakers(segments, turns) == {
        "a": "Paramedic",
        "b": "Paramedic",
    }


def test_maps_role_callout_to_the_next_speaker_only() -> None:
    segments = [
        segment("a", 0, 2_000, "Paramedics, give me the report."),
        segment("b", 2_200, 4_000, "We found the patient awake."),
    ]
    turns = [
        SpeakerTurn(0, 2_000, "SPEAKER_00"),
        SpeakerTurn(2_100, 4_000, "SPEAKER_01"),
    ]

    assert assign_speakers(segments, turns) == {
        "a": "Speaker 1",
        "b": "Paramedic",
    }


def test_uses_role_prefix_for_each_line_even_when_voice_is_the_same() -> None:
    segments = [
        segment("a", 0, 2_000, "Doctor, measure the BP 90 over 60."),
        segment("b", 2_100, 4_000, "Nurse, take the blood."),
    ]
    turns = [SpeakerTurn(0, 4_000, "SPEAKER_00")]

    assert assign_speakers(segments, turns) == {
        "a": "Doctor",
        "b": "Nurse",
    }


def test_role_prefix_still_works_when_diarization_misses_a_short_line() -> None:
    segments = [segment("a", 0, 800, "Nurse, take the blood.")]

    assert assign_speakers(segments, []) == {"a": "Nurse"}
