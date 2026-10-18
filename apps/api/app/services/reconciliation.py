from __future__ import annotations

from app.db.database import Database
from app.models.schemas import (
    ClinicalEvent,
    EventState,
    ReviewItemPatch,
    ReviewItemStatus,
)


OPEN_ACTION_STATES = {
    EventState.PROPOSED,
    EventState.REQUESTED,
    EventState.ACKNOWLEDGED,
    EventState.IN_PROGRESS,
}
EXECUTION_STATES = {EventState.IN_PROGRESS, EventState.COMPLETED}


class EventReconciler:
    def __init__(self, database: Database):
        self.database = database

    def reconcile(self, event: ClinicalEvent) -> None:
        prior = [
            candidate
            for candidate in self.database.list_events(event.session_id)
            if candidate.id != event.id
            and candidate.normalized_action == event.normalized_action
            and abs(candidate.utterance_time_ms - event.utterance_time_ms) <= 300_000
        ]

        if event.state in OPEN_ACTION_STATES:
            self.database.add_review_item(
                event.session_id,
                [event.id],
                f"Was {event.description.removesuffix('.').lower()} later confirmed?",
                "MISSING_CONFIRMATION",
                "DOCUMENTATION",
            )

        if event.state in EXECUTION_STATES:
            for item in self.database.list_review_items(event.session_id):
                if item.status != ReviewItemStatus.OPEN or item.reason != "MISSING_CONFIRMATION":
                    continue
                linked = [candidate for candidate in prior if candidate.id in item.related_event_ids]
                if linked:
                    self.database.patch_review_item(
                        item.id,
                        ReviewItemPatch(
                            status=ReviewItemStatus.RESOLVED,
                            resolution=(
                                f"Later evidence captured at {event.utterance_time_ms} ms: "
                                f"{event.evidence_text}"
                            ),
                        ),
                    )

        conflicting = [
            candidate
            for candidate in prior
            if (
                candidate.state == EventState.NEGATED
                and event.state in EXECUTION_STATES
            )
            or (
                event.state == EventState.NEGATED
                and candidate.state in EXECUTION_STATES
            )
        ]
        if conflicting:
            ids = [conflicting[-1].id, event.id]
            if not any(
                item.reason == "CONFLICTING_REPORTS"
                and set(item.related_event_ids) == set(ids)
                for item in self.database.list_review_items(event.session_id)
            ):
                self.database.add_review_item(
                    event.session_id,
                    ids,
                    "Conflicting verbal reports were captured. Which statement should the draft reflect?",
                    "CONFLICTING_REPORTS",
                    "REVIEW",
                )

        if event.state == EventState.UNCERTAIN:
            self.database.add_review_item(
                event.session_id,
                [event.id],
                "Clarify this question or ambiguous statement before finalizing the report.",
                "UNCERTAIN_LANGUAGE",
                "REVIEW",
            )


    def rebuild_open_items(self, session_id: str) -> None:
        """Resolve stale missing-confirmation items after reviewer state edits."""
        events = self.database.list_events(session_id)
        by_id = {event.id: event for event in events}
        for item in self.database.list_review_items(session_id):
            if item.status != ReviewItemStatus.OPEN or item.reason != "MISSING_CONFIRMATION":
                continue
            source = next((by_id[event_id] for event_id in item.related_event_ids if event_id in by_id), None)
            if source is None:
                continue
            later = next(
                (
                    event
                    for event in events
                    if event.normalized_action == source.normalized_action
                    and event.utterance_time_ms >= source.utterance_time_ms
                    and event.state in EXECUTION_STATES
                ),
                None,
            )
            if later:
                self.database.patch_review_item(
                    item.id,
                    ReviewItemPatch(
                        status=ReviewItemStatus.RESOLVED,
                        resolution=f"Later transcript evidence: {later.evidence_text}",
                    ),
                )

