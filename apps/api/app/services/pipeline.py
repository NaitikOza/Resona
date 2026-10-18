from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.db.database import Database
from app.models.schemas import ClinicalEvent, TranscriptSegment, TranscriptSegmentCreate
from app.services.extraction import DeterministicExtractor
from app.services.reconciliation import EventReconciler


class EvidencePipeline:
    def __init__(self, database: Database):
        self.database = database
        self.extractor = DeterministicExtractor()
        self.reconciler = EventReconciler(database)

    def ingest(
        self, session_id: str, payload: TranscriptSegmentCreate
    ) -> tuple[TranscriptSegment, list[ClinicalEvent]]:
        duplicate = self._duplicate_segment(session_id, payload)
        if duplicate is not None:
            return duplicate, []
        segment = self.database.add_segment(session_id, payload)
        events: list[ClinicalEvent] = []
        for candidate in self.extractor.extract(segment):
            if self._is_duplicate(candidate.normalized_action, candidate.state.value, segment):
                continue
            event = self.database.add_event(session_id, candidate, origin="rules")
            self.reconciler.reconcile(event)
            events.append(event)
        return segment, events

    def _duplicate_segment(
        self, session_id: str, payload: TranscriptSegmentCreate
    ) -> TranscriptSegment | None:
        normalized = self._normalized_text(payload.raw_text)
        for existing in reversed(self.database.list_segments(session_id)[-8:]):
            overlap_ms = max(
                0,
                min(existing.end_ms, payload.end_ms)
                - max(existing.start_ms, payload.start_ms),
            )
            shorter_duration = max(
                1,
                min(
                    existing.end_ms - existing.start_ms,
                    payload.end_ms - payload.start_ms,
                ),
            )
            similarity = SequenceMatcher(
                None, self._normalized_text(existing.display_text), normalized
            ).ratio()
            if overlap_ms / shorter_duration >= 0.5 and similarity >= 0.94:
                return existing
        return None

    @staticmethod
    def _normalized_text(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    def _is_duplicate(
        self, normalized_action: str, state: str, segment: TranscriptSegment
    ) -> bool:
        for event in self.database.list_events(segment.session_id):
            if (
                event.normalized_action == normalized_action
                and event.state.value == state
                and event.evidence_text.casefold() == segment.display_text.casefold()
                and abs(event.utterance_time_ms - segment.start_ms) <= 1_500
            ):
                return True
        return False

