from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.schemas import (
    ClinicalEventCreate,
    EventCategory,
    EventEntity,
    EventState,
    TranscriptSegment,
)


@dataclass(frozen=True)
class ActionDefinition:
    action: str
    category: EventCategory
    phrases: tuple[str, ...]
    label: str


ACTIONS: tuple[ActionDefinition, ...] = (
    ActionDefinition(
        "transfuse_blood_product",
        EventCategory.FLUID_OR_BLOOD_PRODUCT,
        ("blood", "transfusion", "units", "packed red", "plasma"),
        "Blood product",
    ),
    ActionDefinition(
        "establish_iv_access",
        EventCategory.PROCEDURE,
        ("iv", "intravenous", "vascular access", "line is in"),
        "IV access",
    ),
    ActionDefinition(
        "perform_intubation",
        EventCategory.PROCEDURE,
        ("intubat", "endotracheal", "airway tube", "tube is in"),
        "Intubation",
    ),
    ActionDefinition(
        "administer_medication",
        EventCategory.MEDICATION,
        (
            "medication",
            "medicine",
            "drug",
            "epinephrine",
            "ketamine",
            "fentanyl",
            "cefazolin",
            "antibiotic",
        ),
        "Medication",
    ),
    ActionDefinition(
        "administer_fluid",
        EventCategory.FLUID_OR_BLOOD_PRODUCT,
        ("fluid", "saline", "lactated ringer", "bolus"),
        "Fluid",
    ),
    ActionDefinition(
        "obtain_imaging",
        EventCategory.IMAGING_OR_TEST,
        ("ct", "x-ray", "xray", "ultrasound", "scan", "imaging"),
        "Imaging",
    ),
    ActionDefinition(
        "obtain_test",
        EventCategory.IMAGING_OR_TEST,
        ("lab", "test", "cbc", "blood gas", "result"),
        "Test",
    ),
    ActionDefinition(
        "apply_equipment",
        EventCategory.EQUIPMENT,
        ("monitor", "equipment", "splint", "collar", "tourniquet"),
        "Equipment",
    ),
    ActionDefinition(
        "communicate_or_consult",
        EventCategory.CONSULT_OR_COMMUNICATION,
        ("consult", "call", "notify", "page", "transfer"),
        "Communication",
    ),
)


MEASUREMENT_PATTERN = re.compile(
    r"\b(?:blood pressure|bp|heart rate|pulse|temperature|oxygen saturation|spo2|gcs)\b",
    re.IGNORECASE,
)
OBSERVATION_PATTERN = re.compile(
    r"\b(?:no pulse|awake|alert|unresponsive|responsive|bleeding|tenderness|breath sounds|"
    r"pupils?|airway (?:is )?(?:clear|patent)|result (?:is|shows)|reported)\b",
    re.IGNORECASE,
)
QUESTION_PATTERN = re.compile(
    r"^\s*(?:did|do|does|has|have|is|are|was|were|can|could|should|where|what|when|who)\b|\?",
    re.IGNORECASE,
)
POLITE_REQUEST_PATTERN = re.compile(
    r"\b(?:can somebody|can someone|could somebody|could someone)\b", re.IGNORECASE
)
NEGATION_PATTERN = re.compile(
    r"\b(?:no|not|never|hasn['’]?t|haven['’]?t|wasn['’]?t|weren['’]?t|didn['’]?t|without)\b",
    re.IGNORECASE,
)
CANCEL_PATTERN = re.compile(
    r"\b(?:cancel|cancelled|canceled|stop that|discontinue|hold off|don['’]?t do)\b",
    re.IGNORECASE,
)
COMPLETED_PATTERN = re.compile(
    r"\b(?:completed|finished|done|established|is in and flushing|has been given|was given|"
    r"administered|is secured|procedure complete|result is back|result shows)\b",
    re.IGNORECASE,
)
IN_PROGRESS_PATTERN = re.compile(
    r"\b(?:starting|started|beginning|in progress|administering|giving now|running now|"
    r"transfusion has started|placing now|inserting now|preparing|getting (?:the )?.+ ready)\b",
    re.IGNORECASE,
)
ACK_PATTERN = re.compile(
    r"^\s*(?:okay|ok|copy|copied|understood|will do|on it|acknowledged)\b",
    re.IGNORECASE,
)
PROPOSED_PATTERN = re.compile(
    r"\b(?:might|may|could|consider|thinking about|plan to|planning to|we should|we may need)\b",
    re.IGNORECASE,
)
REQUEST_PATTERN = re.compile(
    r"\b(?:please|prepare|order|request|get|bring|give|obtain|send|place|start|begin|"
    r"can somebody|can someone|we need|i need|let['’]?s)\b",
    re.IGNORECASE,
)
QUANTITY_PATTERN = re.compile(
    r"\b(?P<number>\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(?P<unit>mg|mcg|g|ml|mL|l|L|units?|milligrams?|micrograms?|liters?|cc|%)\b",
    re.IGNORECASE,
)
UNPUNCTUATED_BOUNDARY_PATTERN = re.compile(
    r"\s+(?=(?:can somebody|can someone|could somebody|could someone|"
    r"starting\b|beginning\b|prepare\b|order\b|request\b|please\b|"
    r"did\b|cancel\b|we (?:may|might|need|should|plan)\b|"
    r"(?:iv|intravenous|vascular access|line|tube|intubation|transfusion|"
    r"medication|blood|ct|x-ray|xray|ultrasound|scan|imaging|test|equipment) "
    r"(?:is|has|was)\b))",
    re.IGNORECASE,
)


class DeterministicExtractor:
    version = "rules-v1"

    def extract(self, segment: TranscriptSegment) -> list[ClinicalEventCreate]:
        text = segment.display_text.strip()
        if not text:
            return []

        clauses = self._split_clauses(text)
        if not clauses:
            return []
        duration_ms = max(1, segment.end_ms - segment.start_ms)
        events: list[ClinicalEventCreate] = []
        for clause, clause_start in clauses:
            clause_start_ms = segment.start_ms + int(
                duration_ms * clause_start / max(1, len(text))
            )
            event = self._extract_clause(segment, clause, clause_start_ms)
            if event is not None:
                events.append(event)
        return events

    @staticmethod
    def _split_clauses(text: str) -> list[tuple[str, int]]:
        clauses: list[tuple[str, int]] = []
        for sentence in re.finditer(r"[^.!?;]+(?:[.!?;]+|$)", text):
            raw = sentence.group(0)
            boundaries = [
                match.end()
                for match in UNPUNCTUATED_BOUNDARY_PATTERN.finditer(raw)
                if not re.search(
                    r"\b(?:no|not|never|without)$",
                    raw[: match.start()].rstrip(),
                    re.IGNORECASE,
                )
            ]
            cuts = [
                0,
                *boundaries,
                len(raw),
            ]
            for start, end in zip(cuts, cuts[1:]):
                candidate = raw[start:end]
                left_trimmed = candidate.lstrip()
                if not left_trimmed:
                    continue
                clause = left_trimmed.rstrip()
                offset = sentence.start() + start + len(candidate) - len(left_trimmed)
                clauses.append((clause, offset))
        return clauses

    def _extract_clause(
        self, segment: TranscriptSegment, text: str, utterance_time_ms: int
    ) -> ClinicalEventCreate | None:
        definition = self._match_action(text)
        category = definition.category if definition else None
        action = definition.action if definition else None
        label = definition.label if definition else None

        if definition and definition.action == "transfuse_blood_product":
            folded = text.casefold()
            if any(cue in folded for cue in ("prepare", "getting the blood ready", "blood ready")):
                action = "prepare_blood_product"
                label = "Blood product preparation"
            elif any(cue in folded for cue in ("arrive", "available", "get the blood", "bring blood")):
                action = "obtain_blood_product"
                label = "Blood product availability"
            elif any(cue in folded for cue in ("might need", "may need", "consider")):
                action = "consider_blood_product"
                label = "Blood product use"

        if OBSERVATION_PATTERN.search(text) and definition is None:
            category = EventCategory.OBSERVATION
            action = "record_observation"
            label = "Reported observation"
        elif MEASUREMENT_PATTERN.search(text):
            category = EventCategory.MEASUREMENT
            action = "record_measurement"
            label = "Reported measurement"

        if category is None or action is None or label is None:
            return None

        state = self._classify_state(text, category)
        confidence = segment.confidence
        if confidence < 0.55:
            state = EventState.UNCERTAIN

        entities = self._extract_entities(text)
        requires_review = (
            confidence < 0.85
            or state in {EventState.UNCERTAIN, EventState.NEGATED, EventState.CANCELLED}
            or bool(entities)
            or category in {EventCategory.MEDICATION, EventCategory.PROCEDURE}
        )
        description = self._description(label, state, text)
        return ClinicalEventCreate(
            category=category,
            normalized_action=action,
            state=state,
            utterance_time_ms=utterance_time_ms,
            asserted_action_time_ms=None,
            description=description,
            source_segment_ids=[segment.id],
            evidence_text=text,
            confidence=confidence,
            requires_review=requires_review,
            entities=entities,
        )

    @staticmethod
    def _match_action(text: str) -> ActionDefinition | None:
        folded = text.casefold()
        for definition in ACTIONS:
            if any(
                re.search(rf"\b{re.escape(phrase)}", folded)
                for phrase in definition.phrases
            ):
                return definition
        return None

    @staticmethod
    def _classify_state(text: str, category: EventCategory) -> EventState:
        if QUESTION_PATTERN.search(text) and not POLITE_REQUEST_PATTERN.search(text):
            return EventState.UNCERTAIN
        if CANCEL_PATTERN.search(text):
            return EventState.CANCELLED
        if category in {EventCategory.OBSERVATION, EventCategory.MEASUREMENT}:
            return EventState.REPORTED
        if category == EventCategory.IMAGING_OR_TEST and re.search(
            r"\b(?:result|shows|reported|is back)\b", text, re.IGNORECASE
        ):
            return EventState.REPORTED
        if NEGATION_PATTERN.search(text):
            return EventState.NEGATED
        if COMPLETED_PATTERN.search(text):
            return EventState.COMPLETED
        if IN_PROGRESS_PATTERN.search(text):
            return EventState.IN_PROGRESS
        if PROPOSED_PATTERN.search(text):
            return EventState.PROPOSED
        if ACK_PATTERN.search(text):
            return EventState.ACKNOWLEDGED
        if REQUEST_PATTERN.search(text):
            return EventState.REQUESTED
        if category in {
            EventCategory.OBSERVATION,
            EventCategory.MEASUREMENT,
            EventCategory.IMAGING_OR_TEST,
        }:
            return EventState.REPORTED
        return EventState.UNCERTAIN

    @staticmethod
    def _extract_entities(text: str) -> list[EventEntity]:
        entities: list[EventEntity] = []
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        for match in QUANTITY_PATTERN.finditer(text):
            raw_number = match.group("number")
            numeric = float(words.get(raw_number.casefold(), raw_number))
            entities.append(
                EventEntity(
                    entity_type="quantity",
                    normalized_name=None,
                    verbatim_value=match.group(0),
                    numeric_value=numeric,
                    unit=match.group("unit"),
                    source_span=(match.start(), match.end()),
                )
            )
        return entities

    @staticmethod
    def _description(label: str, state: EventState, text: str) -> str:
        wording = {
            EventState.PROPOSED: "proposed",
            EventState.REQUESTED: "requested",
            EventState.ACKNOWLEDGED: "acknowledged (execution not established)",
            EventState.IN_PROGRESS: "explicitly described as in progress",
            EventState.COMPLETED: "explicitly described as completed",
            EventState.CANCELLED: "explicitly cancelled",
            EventState.NEGATED: "explicitly reported as not performed",
            EventState.UNCERTAIN: "unclear or posed as a question",
            EventState.REPORTED: "reported in the conversation",
        }[state]
        return f"{label} {wording}."

