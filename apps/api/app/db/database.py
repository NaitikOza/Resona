from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.models.schemas import (
    AuditEntry,
    ClinicalEvent,
    ClinicalEventCreate,
    EventPatch,
    ReportRecord,
    ReviewItem,
    ReviewItemPatch,
    ReviewItemStatus,
    ReviewStatus,
    SegmentReviewStatus,
    SessionCreate,
    SessionRecord,
    SessionStatus,
    TranscriptPatch,
    TranscriptSegment,
    TranscriptSegmentCreate,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
INSERT INTO schema_meta(version)
SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_meta);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    case_label TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    simulation_flag INTEGER NOT NULL DEFAULT 1,
    consent_recorded INTEGER NOT NULL,
    model_versions TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audio_chunks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    local_path TEXT,
    checksum TEXT,
    processing_status TEXT NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    corrected_text TEXT,
    speaker_label TEXT NOT NULL,
    asr_engine TEXT NOT NULL,
    confidence REAL NOT NULL,
    review_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    normalized_action TEXT NOT NULL,
    state TEXT NOT NULL,
    utterance_time_ms INTEGER NOT NULL,
    asserted_action_time_ms INTEGER,
    description TEXT NOT NULL,
    source_segment_ids TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    confidence REAL NOT NULL,
    requires_review INTEGER NOT NULL,
    reviewer_status TEXT NOT NULL,
    origin TEXT NOT NULL,
    entities TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_entities (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    normalized_name TEXT,
    verbatim_value TEXT NOT NULL,
    numeric_value REAL,
    unit TEXT,
    source_span TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_links (
    id TEXT PRIMARY KEY,
    from_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    to_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,
    rationale TEXT NOT NULL,
    review_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_items (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    related_event_ids TEXT NOT NULL,
    question TEXT NOT NULL,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    resolution TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_audit (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    changed_at TEXT NOT NULL,
    previous_value TEXT NOT NULL,
    updated_value TEXT NOT NULL,
    actor TEXT NOT NULL,
    change_reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    generated_at TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    reviewed_status TEXT NOT NULL,
    structured_json TEXT NOT NULL,
    final_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_segments_session_time
ON transcript_segments(session_id, start_ms);
CREATE INDEX IF NOT EXISTS idx_events_session_time
ON events(session_id, utterance_time_ms);
CREATE INDEX IF NOT EXISTS idx_review_session
ON review_items(session_id, status);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def create_session(self, payload: SessionCreate) -> SessionRecord:
        session_id = str(uuid4())
        created_at = utc_now()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO sessions
                (id, case_label, mode, status, created_at, simulation_flag,
                 consent_recorded, model_versions)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    session_id,
                    payload.case_label,
                    payload.mode.value,
                    SessionStatus.CREATED.value,
                    created_at.isoformat(),
                    int(payload.consent_recorded),
                    _json({"extraction": "rules-v1", "llm": "disabled"}),
                ),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> SessionRecord:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Session not found")
        return self._session(row)

    def list_sessions(self) -> list[SessionRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [self._session(row) for row in rows]

    def transition_session(
        self, session_id: str, status: SessionStatus, duration_ms: int | None = None
    ) -> SessionRecord:
        current = self.get_session(session_id)
        allowed: dict[SessionStatus, set[SessionStatus]] = {
            SessionStatus.CREATED: {SessionStatus.RECORDING, SessionStatus.PROCESSING},
            SessionStatus.RECORDING: {
                SessionStatus.PAUSED,
                SessionStatus.PROCESSING,
                SessionStatus.READY_FOR_REVIEW,
                SessionStatus.ERROR,
            },
            SessionStatus.PAUSED: {
                SessionStatus.RECORDING,
                SessionStatus.PROCESSING,
                SessionStatus.READY_FOR_REVIEW,
                SessionStatus.ERROR,
            },
            SessionStatus.PROCESSING: {
                SessionStatus.READY_FOR_REVIEW,
                SessionStatus.ERROR,
            },
            SessionStatus.READY_FOR_REVIEW: {
                SessionStatus.COMPLETED,
                SessionStatus.PROCESSING,
            },
            SessionStatus.COMPLETED: {SessionStatus.PROCESSING},
            SessionStatus.ERROR: {SessionStatus.PROCESSING},
        }
        if status != current.status and status not in allowed[current.status]:
            raise ValueError(f"Cannot transition {current.status} to {status}")
        now = utc_now().isoformat()
        fields = ["status = ?", "revision = revision + 1"]
        values: list[Any] = [status.value]
        if status == SessionStatus.RECORDING and current.started_at is None:
            fields.append("started_at = ?")
            values.append(now)
        if status in {SessionStatus.READY_FOR_REVIEW, SessionStatus.COMPLETED}:
            fields.append("ended_at = COALESCE(ended_at, ?)")
            values.append(now)
        if duration_ms is not None:
            fields.append("duration_ms = ?")
            values.append(max(current.duration_ms, duration_ms))
        values.append(session_id)
        with self.connection() as connection:
            connection.execute(
                f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?", values
            )
        return self.get_session(session_id)

    def bump_revision(self, session_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "UPDATE sessions SET revision = revision + 1 WHERE id = ?", (session_id,)
            )

    def delete_session(self, session_id: str) -> bool:
        with self.connection() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    def add_audio_chunk(
        self,
        session_id: str,
        seq: int,
        start_ms: int,
        end_ms: int,
        local_path: str | None,
        checksum: str,
        status: str,
    ) -> str:
        chunk_id = str(uuid4())
        with self.connection() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO audio_chunks
                (id, session_id, seq, start_ms, end_ms, local_path, checksum, processing_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (chunk_id, session_id, seq, start_ms, end_ms, local_path, checksum, status),
            )
        return chunk_id

    def get_audio_path(self, session_id: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT local_path FROM audio_chunks
                WHERE session_id = ? AND local_path IS NOT NULL
                ORDER BY seq LIMIT 1""",
                (session_id,),
            ).fetchone()
        return row["local_path"] if row else None

    def add_segment(
        self, session_id: str, payload: TranscriptSegmentCreate
    ) -> TranscriptSegment:
        session = self.get_session(session_id)
        model_versions = dict(session.model_versions)
        if payload.asr_engine not in {"manual-entry", "curated-scenario"}:
            model_versions["asr"] = payload.asr_engine
        segment_id = str(uuid4())
        created_at = utc_now()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO transcript_segments
                (id, session_id, start_ms, end_ms, raw_text, corrected_text,
                 speaker_label, asr_engine, confidence, review_status, created_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
                (
                    segment_id,
                    session_id,
                    payload.start_ms,
                    payload.end_ms,
                    payload.raw_text.strip(),
                    payload.speaker_label,
                    payload.asr_engine,
                    payload.confidence,
                    SegmentReviewStatus.RAW.value,
                    created_at.isoformat(),
                ),
            )
            connection.execute(
                """UPDATE sessions SET duration_ms = MAX(duration_ms, ?),
                   model_versions = ?, revision = revision + 1 WHERE id = ?""",
                (payload.end_ms, _json(model_versions), session_id),
            )
        return self.get_segment(segment_id)

    def get_segment(self, segment_id: str) -> TranscriptSegment:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM transcript_segments WHERE id = ?", (segment_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Transcript segment not found")
        return self._segment(row)

    def list_segments(self, session_id: str) -> list[TranscriptSegment]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM transcript_segments WHERE session_id = ?
                ORDER BY start_ms, created_at""",
                (session_id,),
            ).fetchall()
        return [self._segment(row) for row in rows]

    def clear_generated_transcript(self, session_id: str) -> None:
        """Remove live-pass transcript data before a more accurate final pass."""
        self.get_session(session_id)
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM review_items WHERE session_id = ?", (session_id,)
            )
            connection.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            connection.execute(
                "DELETE FROM transcript_segments WHERE session_id = ?", (session_id,)
            )
            connection.execute(
                "UPDATE sessions SET revision = revision + 1 WHERE id = ?",
                (session_id,),
            )

    def patch_segment(
        self, segment_id: str, patch: TranscriptPatch
    ) -> TranscriptSegment:
        current = self.get_segment(segment_id)
        updates = patch.model_dump(exclude_none=True, exclude={"change_reason"})
        if not updates:
            return current
        fields: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            fields.append(f"{key} = ?")
            values.append(value.value if hasattr(value, "value") else value)
        values.append(segment_id)
        with self.connection() as connection:
            connection.execute(
                f"UPDATE transcript_segments SET {', '.join(fields)} WHERE id = ?", values
            )
        self.bump_revision(current.session_id)
        return self.get_segment(segment_id)

    def update_speaker_labels(
        self,
        session_id: str,
        assignments: dict[str, str],
        engine: str = "pyannote.audio/community-1",
    ) -> list[TranscriptSegment]:
        if not assignments:
            return self.list_segments(session_id)
        session = self.get_session(session_id)
        segment_ids = {segment.id for segment in self.list_segments(session_id)}
        invalid = set(assignments) - segment_ids
        if invalid:
            raise ValueError("Speaker assignments must reference this session's transcript")
        model_versions = dict(session.model_versions)
        model_versions["diarization"] = engine
        with self.connection() as connection:
            connection.executemany(
                """UPDATE transcript_segments SET speaker_label = ?
                WHERE id = ? AND (speaker_label = 'Unknown' OR speaker_label LIKE 'Speaker %')""",
                [(label, segment_id) for segment_id, label in assignments.items()],
            )
            connection.execute(
                """UPDATE sessions SET model_versions = ?, revision = revision + 1
                WHERE id = ?""",
                (_json(model_versions), session_id),
            )
        return self.list_segments(session_id)

    def add_event(
        self, session_id: str, payload: ClinicalEventCreate, origin: str = "rules"
    ) -> ClinicalEvent:
        valid_segment_ids = {segment.id for segment in self.list_segments(session_id)}
        if not set(payload.source_segment_ids).issubset(valid_segment_ids):
            raise ValueError("Every event must reference an existing transcript segment")
        supporting_text = " ".join(
            segment.display_text
            for segment in self.list_segments(session_id)
            if segment.id in payload.source_segment_ids
        )
        if payload.evidence_text.casefold() not in supporting_text.casefold():
            raise ValueError("Event evidence must appear verbatim in its source transcript")
        event_id = str(uuid4())
        now = utc_now()
        reviewer_status = ReviewStatus.UNVERIFIED
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO events
                (id, session_id, category, normalized_action, state,
                 utterance_time_ms, asserted_action_time_ms, description,
                 source_segment_ids, evidence_text, confidence, requires_review,
                 reviewer_status, origin, entities, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    session_id,
                    payload.category.value,
                    payload.normalized_action,
                    payload.state.value,
                    payload.utterance_time_ms,
                    payload.asserted_action_time_ms,
                    payload.description,
                    _json(payload.source_segment_ids),
                    payload.evidence_text,
                    payload.confidence,
                    int(payload.requires_review),
                    reviewer_status.value,
                    origin,
                    _json([entity.model_dump() for entity in payload.entities]),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            for entity in payload.entities:
                connection.execute(
                    """INSERT INTO event_entities
                    (id, event_id, entity_type, normalized_name, verbatim_value,
                     numeric_value, unit, source_span)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid4()),
                        event_id,
                        entity.entity_type,
                        entity.normalized_name,
                        entity.verbatim_value,
                        entity.numeric_value,
                        entity.unit,
                        _json(entity.source_span),
                    ),
                )
            connection.execute(
                "UPDATE sessions SET revision = revision + 1 WHERE id = ?", (session_id,)
            )
        return self.get_event(event_id)

    def get_event(self, event_id: str) -> ClinicalEvent:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Event not found")
        return self._event(row)

    def list_events(self, session_id: str) -> list[ClinicalEvent]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE session_id = ? ORDER BY utterance_time_ms, created_at",
                (session_id,),
            ).fetchall()
        return [self._event(row) for row in rows]

    def patch_event(self, event_id: str, patch: EventPatch) -> ClinicalEvent:
        current = self.get_event(event_id)
        updates = patch.model_dump(exclude_none=True, exclude={"change_reason"})
        if not updates:
            return current
        previous = current.model_dump(mode="json")
        fields: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            fields.append(f"{key} = ?")
            values.append(value.value if hasattr(value, "value") else value)
        fields.append("updated_at = ?")
        values.append(utc_now().isoformat())
        values.append(event_id)
        with self.connection() as connection:
            connection.execute(f"UPDATE events SET {', '.join(fields)} WHERE id = ?", values)
        updated = self.get_event(event_id)
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO event_audit
                (id, event_id, changed_at, previous_value, updated_value, actor, change_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    event_id,
                    utc_now().isoformat(),
                    _json(previous),
                    _json(updated.model_dump(mode="json")),
                    "reviewer",
                    patch.change_reason,
                ),
            )
        self.bump_revision(current.session_id)
        return updated

    def list_audit(self, session_id: str) -> list[AuditEntry]:
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT a.* FROM event_audit a JOIN events e ON a.event_id = e.id
                WHERE e.session_id = ? ORDER BY a.changed_at""",
                (session_id,),
            ).fetchall()
        return [
            AuditEntry(
                id=row["id"],
                event_id=row["event_id"],
                changed_at=row["changed_at"],
                previous_value=json.loads(row["previous_value"]),
                updated_value=json.loads(row["updated_value"]),
                actor=row["actor"],
                change_reason=row["change_reason"],
            )
            for row in rows
        ]

    def add_review_item(
        self,
        session_id: str,
        related_event_ids: list[str],
        question: str,
        reason: str,
        severity: str = "REVIEW",
    ) -> ReviewItem:
        item_id = str(uuid4())
        created_at = utc_now()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO review_items
                (id, session_id, related_event_ids, question, reason, severity,
                 status, resolution, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (
                    item_id,
                    session_id,
                    _json(related_event_ids),
                    question,
                    reason,
                    severity,
                    ReviewItemStatus.OPEN.value,
                    created_at.isoformat(),
                ),
            )
        return self.get_review_item(item_id)

    def get_review_item(self, item_id: str) -> ReviewItem:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM review_items WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Review item not found")
        return self._review_item(row)

    def list_review_items(self, session_id: str) -> list[ReviewItem]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM review_items WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return [self._review_item(row) for row in rows]

    def patch_review_item(
        self, item_id: str, patch: ReviewItemPatch
    ) -> ReviewItem:
        current = self.get_review_item(item_id)
        with self.connection() as connection:
            connection.execute(
                "UPDATE review_items SET status = ?, resolution = ? WHERE id = ?",
                (patch.status.value, patch.resolution, item_id),
            )
        self.bump_revision(current.session_id)
        return self.get_review_item(item_id)

    def add_report(
        self,
        session_id: str,
        source_revision: int,
        reviewed_status: str,
        structured_json: dict[str, Any],
        final_text: str,
    ) -> ReportRecord:
        report_id = str(uuid4())
        generated_at = utc_now()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO reports
                (id, session_id, generated_at, source_revision, reviewed_status,
                 structured_json, final_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id,
                    session_id,
                    generated_at.isoformat(),
                    source_revision,
                    reviewed_status,
                    _json(structured_json),
                    final_text,
                ),
            )
        return self.get_latest_report(session_id)

    def get_latest_report(self, session_id: str) -> ReportRecord:
        with self.connection() as connection:
            row = connection.execute(
                """SELECT * FROM reports WHERE session_id = ?
                ORDER BY generated_at DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError("No report has been generated")
        return ReportRecord(
            id=row["id"],
            session_id=row["session_id"],
            generated_at=row["generated_at"],
            source_revision=row["source_revision"],
            reviewed_status=row["reviewed_status"],
            structured_json=json.loads(row["structured_json"]),
            final_text=row["final_text"],
        )

    @staticmethod
    def _session(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            case_label=row["case_label"],
            mode=row["mode"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            simulation_flag=bool(row["simulation_flag"]),
            consent_recorded=bool(row["consent_recorded"]),
            model_versions=json.loads(row["model_versions"]),
            duration_ms=row["duration_ms"],
            revision=row["revision"],
        )

    @staticmethod
    def _segment(row: sqlite3.Row) -> TranscriptSegment:
        return TranscriptSegment(
            id=row["id"],
            session_id=row["session_id"],
            start_ms=row["start_ms"],
            end_ms=row["end_ms"],
            raw_text=row["raw_text"],
            corrected_text=row["corrected_text"],
            speaker_label=row["speaker_label"],
            asr_engine=row["asr_engine"],
            confidence=row["confidence"],
            review_status=row["review_status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> ClinicalEvent:
        return ClinicalEvent(
            id=row["id"],
            session_id=row["session_id"],
            category=row["category"],
            normalized_action=row["normalized_action"],
            state=row["state"],
            utterance_time_ms=row["utterance_time_ms"],
            asserted_action_time_ms=row["asserted_action_time_ms"],
            description=row["description"],
            source_segment_ids=json.loads(row["source_segment_ids"]),
            evidence_text=row["evidence_text"],
            confidence=row["confidence"],
            requires_review=bool(row["requires_review"]),
            reviewer_status=row["reviewer_status"],
            origin=row["origin"],
            entities=json.loads(row["entities"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _review_item(row: sqlite3.Row) -> ReviewItem:
        return ReviewItem(
            id=row["id"],
            session_id=row["session_id"],
            related_event_ids=json.loads(row["related_event_ids"]),
            question=row["question"],
            reason=row["reason"],
            severity=row["severity"],
            status=row["status"],
            resolution=row["resolution"],
            created_at=row["created_at"],
        )

