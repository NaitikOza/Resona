from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models.schemas import (
    EventState,
    SegmentReviewStatus,
    TranscriptSegment,
)
from app.services.extraction import DeterministicExtractor


def segment(text: str, confidence: float = 1.0) -> TranscriptSegment:
    return TranscriptSegment(
        id="seg-test",
        session_id="session-test",
        start_ms=1200,
        end_ms=3200,
        raw_text=text,
        corrected_text=None,
        speaker_label="Unknown",
        asr_engine="test",
        confidence=confidence,
        review_status=SegmentReviewStatus.RAW,
        created_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    ("text", "action", "state"),
    [
        ("We may need to intubate.", "perform_intubation", EventState.PROPOSED),
        ("Start intubation.", "perform_intubation", EventState.REQUESTED),
        ("Starting the IV now.", "establish_iv_access", EventState.IN_PROGRESS),
        ("IV is established.", "establish_iv_access", EventState.COMPLETED),
        ("Cancel the intubation plan.", "perform_intubation", EventState.CANCELLED),
        ("No medication was given.", "administer_medication", EventState.NEGATED),
        ("Did we give the medication?", "administer_medication", EventState.UNCERTAIN),
        ("Can somebody get an IV?", "establish_iv_access", EventState.REQUESTED),
        ("Blood pressure is ninety over sixty.", "record_measurement", EventState.REPORTED),
        ("No pulse.", "record_observation", EventState.REPORTED),
        ("CT result is back, no bleed reported.", "obtain_imaging", EventState.REPORTED),
    ],
)
def test_state_classification(text: str, action: str, state: EventState) -> None:
    events = DeterministicExtractor().extract(segment(text))
    assert len(events) == 1
    assert events[0].normalized_action == action
    assert events[0].state == state
    assert events[0].evidence_text == text


def test_blood_preparation_never_becomes_administration() -> None:
    event = DeterministicExtractor().extract(segment("Prepare two units of blood."))[0]
    assert event.normalized_action == "prepare_blood_product"
    assert event.state == EventState.REQUESTED
    assert event.state != EventState.COMPLETED
    assert event.entities[0].numeric_value == 2
    assert event.entities[0].unit == "units"


def test_transfusion_start_is_not_completion() -> None:
    event = DeterministicExtractor().extract(segment("The transfusion has started."))[0]
    assert event.normalized_action == "transfuse_blood_product"
    assert event.state == EventState.IN_PROGRESS


def test_low_confidence_becomes_uncertain_and_requires_review() -> None:
    event = DeterministicExtractor().extract(segment("IV is established.", confidence=0.4))[0]
    assert event.state == EventState.UNCERTAIN
    assert event.requires_review is True


def test_irrelevant_conversation_produces_no_event() -> None:
    assert DeterministicExtractor().extract(segment("Thank you everyone.")) == []


def test_multi_utterance_asr_segment_emits_individual_evidence_events() -> None:
    events = DeterministicExtractor().extract(
        segment(
            "Blood pressure is 90 over 60. Can somebody get an IV? "
            "Starting the IV now. IV is established."
        )
    )
    assert [(event.normalized_action, event.state) for event in events] == [
        ("record_measurement", EventState.REPORTED),
        ("establish_iv_access", EventState.REQUESTED),
        ("establish_iv_access", EventState.IN_PROGRESS),
        ("establish_iv_access", EventState.COMPLETED),
    ]
    assert [event.evidence_text for event in events] == [
        "Blood pressure is 90 over 60.",
        "Can somebody get an IV?",
        "Starting the IV now.",
        "IV is established.",
    ]
    assert [event.utterance_time_ms for event in events] == sorted(
        event.utterance_time_ms for event in events
    )


def test_unpunctuated_asr_segment_keeps_distinct_action_states() -> None:
    events = DeterministicExtractor().extract(
        segment(
            "blood pressure is 90 over 60 can somebody get an IV starting the IV now "
            "IV is established prepare two units of blood did the blood arrive"
        )
    )
    assert [(event.normalized_action, event.state) for event in events] == [
        ("record_measurement", EventState.REPORTED),
        ("establish_iv_access", EventState.REQUESTED),
        ("establish_iv_access", EventState.IN_PROGRESS),
        ("establish_iv_access", EventState.COMPLETED),
        ("prepare_blood_product", EventState.REQUESTED),
        ("obtain_blood_product", EventState.UNCERTAIN),
    ]
    assert [event.evidence_text for event in events] == [
        "blood pressure is 90 over 60",
        "can somebody get an IV",
        "starting the IV now",
        "IV is established",
        "prepare two units of blood",
        "did the blood arrive",
    ]

