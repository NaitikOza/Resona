from __future__ import annotations

from datetime import UTC, datetime

import json
from pathlib import Path

from app.models.schemas import SegmentReviewStatus, TranscriptSegment
from app.services.extraction import DeterministicExtractor


SCENARIOS = Path(__file__).resolve().parents[3] / "scenarios/annotations"


def test_all_eight_reference_scenarios_match_expected_states() -> None:
    files = sorted(SCENARIOS.glob("*.json"))
    assert len(files) >= 8
    extractor = DeterministicExtractor()
    for path in files:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        actual: list[tuple[str, str]] = []
        for index, raw in enumerate(scenario["segments"]):
            segment = TranscriptSegment(
                id=f"seg-{index}",
                session_id="scenario",
                start_ms=raw["start_ms"],
                end_ms=raw["end_ms"],
                raw_text=raw["text"],
                corrected_text=None,
                speaker_label=raw.get("speaker", "Unknown"),
                asr_engine="reference",
                confidence=raw.get("confidence", 1.0),
                review_status=SegmentReviewStatus.RAW,
                created_at=datetime.now(UTC),
            )
            actual.extend(
                (event.normalized_action, event.state.value)
                for event in extractor.extract(segment)
            )
        expected = [
            (event["action"], event["state"]) for event in scenario["expected_events"]
        ]
        assert actual == expected, path.name

