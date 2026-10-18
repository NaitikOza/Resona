from app.api.websocket import stable_segments
from app.models.schemas import TranscriptSegmentCreate


def segment(start_ms: int, end_ms: int, text: str) -> TranscriptSegmentCreate:
    return TranscriptSegmentCreate(
        start_ms=start_ms,
        end_ms=end_ms,
        raw_text=text,
        speaker_label="Unknown",
        asr_engine="whisper.cpp/medium.en",
        confidence=0.9,
    )


def test_live_window_keeps_stable_speech_and_defers_trailing_edge() -> None:
    result = stable_segments(
        [
            segment(0, 2100, "Blood pressure is 90 over 60."),
            segment(3880, 5000, "Starting the IV"),
        ],
        window_start=0,
        window_end=5000,
        overlap_ms=2000,
        first_window=True,
        flush=False,
    )

    assert [item.raw_text for item in result] == ["Blood pressure is 90 over 60."]


def test_overlapping_window_drops_leading_repeat_and_keeps_complete_phrase() -> None:
    result = stable_segments(
        [
            segment(3200, 3900, "an IV?"),
            segment(3880, 5400, "Starting the IV now."),
            segment(5400, 6920, "IV is established."),
            segment(6920, 8000, "Prepare two units"),
        ],
        window_start=3000,
        window_end=8000,
        overlap_ms=2000,
        first_window=False,
        flush=False,
    )

    assert [item.raw_text for item in result] == [
        "Starting the IV now.",
        "IV is established.",
    ]


def test_final_flush_keeps_completed_trailing_speech() -> None:
    result = stable_segments(
        [
            segment(6200, 6900, "IV is established."),
            segment(6920, 8720, "Prepare two units of blood."),
            segment(8720, 9660, "Did the blood arrive?"),
        ],
        window_start=6000,
        window_end=9843,
        overlap_ms=2000,
        first_window=False,
        flush=True,
    )

    assert [item.raw_text for item in result] == [
        "Prepare two units of blood.",
        "Did the blood arrive?",
    ]
