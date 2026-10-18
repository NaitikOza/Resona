from __future__ import annotations

from pathlib import Path

import pytest

from app.db.database import Database
from app.models.schemas import (
    ClinicalEventCreate,
    EventCategory,
    EventState,
    SessionCreate,
    SessionMode,
    TranscriptSegmentCreate,
)
from app.services.pipeline import EvidencePipeline
from app.services.reporting import ReportService


@pytest.fixture()
def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "pipeline.sqlite3")
    value.initialize()
    return value


def make_session(database: Database) -> str:
    return database.create_session(
        SessionCreate(
            case_label="Fictional Case Alpha",
            mode=SessionMode.SAMPLE,
            consent_recorded=True,
        )
    ).id


def ingest(
    pipeline: EvidencePipeline, session_id: str, text: str, start_ms: int
):
    return pipeline.ingest(
        session_id,
        TranscriptSegmentCreate(
            start_ms=start_ms,
            end_ms=start_ms + 1800,
            raw_text=text,
            asr_engine="test",
            confidence=1.0,
        ),
    )


def test_conflicting_statements_create_review_item(database: Database) -> None:
    session_id = make_session(database)
    pipeline = EvidencePipeline(database)
    ingest(pipeline, session_id, "No blood has been given.", 0)
    ingest(pipeline, session_id, "The transfusion has started.", 5000)
    items = database.list_review_items(session_id)
    assert any(item.reason == "CONFLICTING_REPORTS" for item in items)
    assert len(database.list_events(session_id)) == 2


def test_later_confirmation_resolves_matching_request(database: Database) -> None:
    session_id = make_session(database)
    pipeline = EvidencePipeline(database)
    ingest(pipeline, session_id, "Get an IV.", 0)
    ingest(pipeline, session_id, "IV is established.", 5000)
    items = database.list_review_items(session_id)
    assert any(item.reason == "MISSING_CONFIRMATION" and item.status == "RESOLVED" for item in items)


def test_unsupported_event_evidence_is_rejected(database: Database) -> None:
    session_id = make_session(database)
    segment, _ = ingest(EvidencePipeline(database), session_id, "Prepare blood.", 0)
    hallucination = ClinicalEventCreate(
        category=EventCategory.FLUID_OR_BLOOD_PRODUCT,
        normalized_action="transfuse_blood_product",
        state=EventState.COMPLETED,
        utterance_time_ms=0,
        description="Blood was administered.",
        source_segment_ids=[segment.id],
        evidence_text="Blood was administered",
        confidence=0.99,
        requires_review=False,
    )
    with pytest.raises(ValueError, match="verbatim"):
        database.add_event(session_id, hallucination, origin="optional-llm")


def test_report_preserves_evidence_without_internal_state_jargon(database: Database) -> None:
    session_id = make_session(database)
    pipeline = EvidencePipeline(database)
    ingest(pipeline, session_id, "Prepare two units of blood.", 0)
    report = ReportService(database).generate(session_id)
    assert report.reviewed_status == "REVIEW_REQUIRED"
    assert report.structured_json["timeline"][0]["summary"] == "Blood product preparation"
    assert report.structured_json["timeline"][0]["evidence"] == "Prepare two units of blood."
    assert "confidence" not in report.structured_json["timeline"][0]
    assert "state" not in report.structured_json["timeline"][0]
    assert "Prepare two units of blood." in report.final_text
    feedback = report.structured_json["session_feedback"]
    assert any("requested blood arrives" in item for item in feedback["improvements"])
    assert any("transfusion start" in item.lower() for item in feedback["missing"])
    assert "Session feedback" in report.final_text


def test_report_feedback_is_specific_to_closed_loop_iv_case(database: Database) -> None:
    session_id = make_session(database)
    pipeline = EvidencePipeline(database)
    ingest(pipeline, session_id, "Can somebody get an IV?", 0)
    ingest(pipeline, session_id, "Starting the IV now.", 2_000)
    ingest(pipeline, session_id, "IV is in and flushing.", 4_000)

    feedback = ReportService(database).generate(session_id).structured_json[
        "session_feedback"
    ]

    assert any("request through placement" in item for item in feedback["done_well"])
    assert any("IV site and catheter size" in item for item in feedback["improvements"])
    assert all("blood" not in item.lower() for items in feedback.values() for item in items)


def test_report_feedback_identifies_case_specific_fluid_gaps(database: Database) -> None:
    session_id = make_session(database)
    pipeline = EvidencePipeline(database)
    ingest(pipeline, session_id, "BP is ninety over sixty.", 0)
    ingest(pipeline, session_id, "Start the fluid bolus now.", 2_000)

    feedback = ReportService(database).generate(session_id).structured_json[
        "session_feedback"
    ]

    assert any("fluid type and volume" in item for item in feedback["improvements"])
    assert any("repeat blood pressure" in item for item in feedback["missing"])


def test_overlapping_asr_windows_are_conservatively_deduplicated(database: Database) -> None:
    session_id = make_session(database)
    pipeline = EvidencePipeline(database)
    first_segment, first_events = pipeline.ingest(
        session_id,
        TranscriptSegmentCreate(
            start_ms=4000,
            end_ms=6500,
            raw_text="Starting the IV now.",
            asr_engine="whisper.cpp",
            confidence=0.9,
        ),
    )
    duplicate_segment, duplicate_events = pipeline.ingest(
        session_id,
        TranscriptSegmentCreate(
            start_ms=4200,
            end_ms=6400,
            raw_text="Starting the IV now",
            asr_engine="whisper.cpp",
            confidence=0.9,
        ),
    )
    assert duplicate_segment.id == first_segment.id
    assert len(first_events) == 1
    assert duplicate_events == []
    assert len(database.list_segments(session_id)) == 1


def test_asr_engine_is_recorded_in_session_provenance(database: Database) -> None:
    session_id = make_session(database)
    EvidencePipeline(database).ingest(
        session_id,
        TranscriptSegmentCreate(
            start_ms=0,
            end_ms=1200,
            raw_text="Prepare two units of blood.",
            asr_engine="whisper.cpp/base.en",
            confidence=0.88,
        ),
    )
    assert database.get_session(session_id).model_versions["asr"] == "whisper.cpp/base.en"

