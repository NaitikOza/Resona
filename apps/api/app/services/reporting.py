from __future__ import annotations

import csv
import html
import io
import re
from datetime import UTC, datetime
from typing import Any

from app.db.database import Database
from app.models.schemas import (
    ClinicalEvent,
    EventState,
    ReportRecord,
    ReviewItemStatus,
    ReviewStatus,
)


def format_time(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1000
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


ACTION_TITLES = {
    "record_measurement": "Measurement recorded",
    "record_observation": "Observation recorded",
    "establish_iv_access": "IV access",
    "perform_intubation": "Intubation",
    "administer_medication": "Medication",
    "administer_fluid": "Fluids",
    "transfuse_blood_product": "Blood product",
    "prepare_blood_product": "Blood product preparation",
    "obtain_blood_product": "Blood product availability",
    "consider_blood_product": "Blood product",
    "obtain_imaging": "Imaging",
    "obtain_test": "Test or lab",
    "apply_equipment": "Equipment",
    "communicate_or_consult": "Communication",
}


class ReportService:
    def __init__(self, database: Database):
        self.database = database

    def generate(self, session_id: str) -> ReportRecord:
        session = self.database.get_session(session_id)
        events = [
            event
            for event in self.database.list_events(session_id)
            if event.reviewer_status != ReviewStatus.REJECTED
        ]
        segments = {
            segment.id: segment for segment in self.database.list_segments(session_id)
        }
        review_items = self.database.list_review_items(session_id)
        audit = self.database.list_audit(session_id)
        open_items = [item for item in review_items if item.status == ReviewItemStatus.OPEN]
        pending_events = [
            event for event in events if event.reviewer_status == ReviewStatus.UNVERIFIED
        ]
        reviewed_status = (
            "REVIEWED_DRAFT" if not open_items and not pending_events else "REVIEW_REQUIRED"
        )

        generated_at = datetime.now(UTC)
        timeline = [self._event_json(event, segments) for event in events]
        case_label = re.sub(
            r"\bfictional\b", "", session.case_label, flags=re.IGNORECASE
        ).strip() or "Patient"
        feedback = self._feedback(events, list(segments.values()), timeline)
        structured: dict[str, Any] = {
            "title": "Resona — Emergency Documentation Report",
            "generated_at": generated_at.isoformat(),
            "case_label": case_label,
            "duration_ms": session.duration_ms,
            "timeline": timeline,
            "handoff_summary": self._handoff_summary(case_label, feedback),
            "session_feedback": feedback,
            "reviewer_edits": [entry.model_dump(mode="json") for entry in audit],
        }
        final_text = self._plain_text(structured)
        return self.database.add_report(
            session_id,
            session.revision,
            reviewed_status,
            structured,
            final_text,
        )

    @staticmethod
    def _event_json(
        event: ClinicalEvent, segments: dict[str, Any]
    ) -> dict[str, Any]:
        summary = (
            event.description
            if event.normalized_action == "reviewer_documented_event"
            or event.reviewer_status == ReviewStatus.EDITED
            else ACTION_TITLES.get(
                event.normalized_action,
                event.normalized_action.replace("_", " ").title(),
            )
        )
        return {
            "id": event.id,
            "speech_time_ms": event.utterance_time_ms,
            "speech_time": format_time(event.utterance_time_ms),
            "category": event.category.value,
            "action": event.normalized_action,
            "summary": summary,
            "evidence": event.evidence_text,
            "speaker": next(
                (
                    segments[segment_id].speaker_label
                    for segment_id in event.source_segment_ids
                    if segment_id in segments
                ),
                "Unknown",
            ),
            "entities": [entity.model_dump(mode="json") for entity in event.entities],
        }

    @staticmethod
    def _plain_text(structured: dict[str, Any]) -> str:
        lines = [
            structured["title"],
            f"Case: {structured['case_label']}",
            f"Duration: {format_time(structured['duration_ms'])}",
            "",
            "Handoff summary",
            structured.get("handoff_summary", "No handoff summary is available."),
        ]
        lines.extend([
            "",
            "Chronological event log",
        ])
        for event in structured["timeline"]:
            lines.append(
                f"[{event['speech_time']}] {event.get('speaker', 'Unknown')} — "
                f"{event['summary']} — “{event['evidence']}”"
            )
        feedback = structured.get("session_feedback", {})
        lines.extend(["", "Session feedback"])
        for heading, key in (
            ("What went well", "done_well"),
            ("Improve next time", "improvements"),
            ("What was missed", "missing"),
        ):
            lines.append(f"{heading}:")
            lines.extend(f"- {item}" for item in feedback.get(key, []))
        return "\n".join(lines)

    @staticmethod
    def _feedback(
        events: list[ClinicalEvent],
        segments: list[Any],
        timeline: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        del segments, timeline  # Feedback is derived from the case evidence below.
        ordered = sorted(events, key=lambda event: event.utterance_time_ms)
        by_action: dict[str, list[ClinicalEvent]] = {}
        for event in ordered:
            by_action.setdefault(event.normalized_action, []).append(event)

        def first(
            action: str, states: set[EventState] | None = None
        ) -> ClinicalEvent | None:
            return next(
                (
                    event
                    for event in by_action.get(action, [])
                    if states is None or event.state in states
                ),
                None,
            )

        def has(action: str, states: set[EventState] | None = None) -> bool:
            return first(action, states) is not None

        def quote(event: ClinicalEvent) -> str:
            text = " ".join(event.evidence_text.split())
            if len(text) > 105:
                text = text[:102].rstrip() + "…"
            return f"“{text}”"

        open_states = {
            EventState.PROPOSED,
            EventState.REQUESTED,
            EventState.ACKNOWLEDGED,
            EventState.IN_PROGRESS,
            EventState.UNCERTAIN,
        }
        completed = {EventState.COMPLETED}
        started = {EventState.IN_PROGRESS, EventState.COMPLETED}
        measurements = [event for event in ordered if event.category.value == "MEASUREMENT"]
        observations = [event for event in ordered if event.category.value == "OBSERVATION"]
        all_evidence = " ".join(event.evidence_text.casefold() for event in ordered)

        done_well: list[str] = []
        if (
            has("establish_iv_access", {EventState.REQUESTED})
            and has("establish_iv_access", {EventState.IN_PROGRESS})
            and has("establish_iv_access", completed)
        ):
            confirmation = first("establish_iv_access", completed)
            done_well.append(
                "IV access was followed from request through placement and confirmation"
                + (f": {quote(confirmation)}" if confirmation else ".")
            )
        if has("transfuse_blood_product", {EventState.NEGATED}) and has(
            "transfuse_blood_product", started
        ):
            started_event = first("transfuse_blood_product", started)
            done_well.append(
                "The change from no blood given to transfusion started was captured"
                + (f": {quote(started_event)}" if started_event else ".")
            )
        if measurements and has("administer_fluid", started):
            fluid = first("administer_fluid", started)
            done_well.append(
                f"The circulation record links {quote(measurements[0])} with "
                f"{quote(fluid) if fluid else 'the fluid intervention'}."
            )
        elif measurements:
            done_well.append(
                f"An objective measurement was stated clearly: {quote(measurements[0])}"
            )
        if observations and has("obtain_imaging", {EventState.REPORTED}):
            imaging = first("obtain_imaging", {EventState.REPORTED})
            done_well.append(
                f"The clinical exam and imaging result were both documented: "
                f"{quote(observations[0])} and {quote(imaging) if imaging else 'the reported result'}"
            )
        elif observations:
            done_well.append(
                f"A patient finding was documented clearly: {quote(observations[0])}"
            )
        if has("perform_intubation", {EventState.PROPOSED}) and has(
            "perform_intubation", {EventState.CANCELLED}
        ):
            done_well.append(
                "The possible need for intubation and the decision to cancel it were both recorded."
            )
        blood_request = first("prepare_blood_product")
        if blood_request and not done_well:
            preparation = first("prepare_blood_product", {EventState.IN_PROGRESS})
            done_well.append(
                f"The blood request was documented: {quote(blood_request)}"
                + (
                    f" Preparation was also acknowledged: {quote(preparation)}"
                    if preparation and preparation.id != blood_request.id
                    else ""
                )
            )
        if len(
            [
                event
                for event in by_action.get("establish_iv_access", [])
                if event.state == EventState.REQUESTED
            ]
        ) > 1 and not done_well:
            done_well.append(
                "The need for additional IV access was communicated by more than one clinician."
            )
        medication = first("administer_medication")
        if medication and not done_well:
            done_well.append(
                f"The intended medication was identified in the record: {quote(medication)}"
            )
        if not done_well:
            active = next(
                (event for event in ordered if event.state not in {EventState.UNCERTAIN}),
                None,
            )
            done_well.append(
                f"The care step was captured with source wording: {quote(active)}"
                if active
                else "The available clinical conversation was retained for review."
            )

        improvements: list[str] = []
        if has("perform_intubation", {EventState.CANCELLED}):
            improvements.append(
                "Document why intubation was cancelled and the airway plan that replaced it."
            )
        if medication and not has("administer_medication", completed):
            improvements.append(
                "Repeat the medication order with the exact dose, unit, and route, then confirm administration and response."
            )
        if (
            has("prepare_blood_product", open_states)
            or has("obtain_blood_product", open_states)
        ) and not has("transfuse_blood_product", started):
            improvements.append(
                "Confirm when the requested blood arrives and state whether transfusion begins."
            )
        if has("transfuse_blood_product", {EventState.IN_PROGRESS}) and not has(
            "transfuse_blood_product", completed
        ):
            improvements.append(
                "State the blood product and amount, then document completion and the patient's response."
            )
        if has("administer_fluid", open_states) and not has(
            "administer_fluid", completed
        ):
            improvements.append(
                "State the fluid type and volume, confirm when the bolus begins and finishes, then record a repeat blood pressure."
            )
        iv_events = by_action.get("establish_iv_access", [])
        if len(
            [event for event in iv_events if event.state == EventState.REQUESTED]
        ) > 1 and not has("establish_iv_access", completed):
            improvements.append(
                "Clarify whether one or two IV sites were intended and identify the site and catheter size for each."
            )
        elif has("establish_iv_access", open_states) and not has(
            "establish_iv_access", completed
        ):
            improvements.append(
                "Confirm successful IV placement, including site, catheter size, and patency."
            )
        elif has("establish_iv_access", completed):
            improvements.append(
                "Add the IV site and catheter size, plus what was given through the line."
            )
        if has("obtain_imaging", {EventState.REPORTED}):
            improvements.append(
                "Document the clinical plan after the imaging result and the next reassessment."
            )
        if not improvements:
            focus = next((ACTION_TITLES.get(event.normalized_action) for event in ordered), None)
            improvements.append(
                f"After {focus.lower()}, document the patient's response and the next reassessment."
                if focus
                else "Document the patient's response and the next reassessment."
            )

        missing: list[str] = []
        if medication and not has("administer_medication", completed):
            missing.append(
                "The record does not establish the medication dose, route, administration, or patient response."
            )
        if (
            has("prepare_blood_product") or has("obtain_blood_product")
        ) and not has("transfuse_blood_product", started):
            missing.append(
                "Blood arrival, transfusion start, and subsequent patient reassessment were not documented."
            )
        if has("transfuse_blood_product", started) and not has(
            "transfuse_blood_product", completed
        ):
            missing.append(
                "Transfusion completion, reaction check, and follow-up vital signs were not documented."
            )
        if has("establish_iv_access", open_states) and not has(
            "establish_iv_access", completed
        ):
            missing.append(
                "Successful IV placement and patency were not documented."
            )
        if has("perform_intubation", {EventState.CANCELLED}) and not re.search(
            r"\b(?:airway (?:is )?(?:clear|patent)|oxygen saturation|spo2|breath sounds)\b",
            all_evidence,
        ):
            missing.append(
                "The record does not include the airway exam, oxygenation, or breathing assessment supporting the decision."
            )
        if measurements and has("administer_fluid", open_states) and len(measurements) < 2:
            missing.append(
                "Fluid administration, completion, and a repeat blood pressure were not documented."
            )
        if not measurements and not any(
            "vital sign" in item.casefold() for item in missing
        ):
            missing.append(
                "No vital signs were documented with the recorded interventions and findings."
            )
        if observations and has("obtain_imaging", {EventState.REPORTED}):
            missing.append(
                "No repeat neurologic assessment or disposition after the imaging result was documented."
            )
        if not missing:
            missing.append(
                "No post-intervention reassessment or final disposition was documented."
            )

        return {
            "done_well": done_well[:2],
            "improvements": improvements[:2],
            "missing": missing[:2],
        }

    @staticmethod
    def _handoff_summary(
        case_label: str, feedback: dict[str, list[str]]
    ) -> str:
        strengths = feedback.get("done_well", [])[:2]
        gaps = feedback.get("missing", [])[:2]

        def sentence(value: str) -> str:
            clean = value.strip()
            return clean if clean.endswith((".", "!", "?", "”")) else f"{clean}."

        parts = [f"Emergency handoff for {case_label}:"]
        parts.extend(sentence(item) for item in strengths)
        if gaps:
            gap_text = " ".join(sentence(item) for item in gaps)
            parts.append(f"Still to confirm: {gap_text}")
        return " ".join(parts)

    @staticmethod
    def html(report: ReportRecord) -> str:
        data = report.structured_json
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(event['speech_time'])}</td>"
            f"<td>{html.escape(event['category'].replace('_', ' ').title())}</td>"
            f"<td>{html.escape(event['summary'])}</td>"
            f"<td>{html.escape(event.get('speaker', 'Unknown'))}</td>"
            f"<td>“{html.escape(event['evidence'])}”</td>"
            "</tr>"
            for event in data["timeline"]
        )
        feedback = data.get("session_feedback", {})
        feedback_html = "".join(
            f"<section class='feedback-card'><h3>{html.escape(title)}</h3><ul>"
            + "".join(
                f"<li>{html.escape(item)}</li>" for item in feedback.get(key, [])
            )
            + "</ul></section>"
            for title, key in (
                ("What went well", "done_well"),
                ("Improve next time", "improvements"),
                ("What was missed", "missing"),
            )
        )
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(data['title'])}</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;color:#18313a;max-width:980px;margin:40px auto;padding:0 28px;line-height:1.5}}
h1{{font-size:26px}}
table{{width:100%;border-collapse:collapse;margin:20px 0}}th,td{{border-bottom:1px solid #d7e0e3;padding:10px;text-align:left;vertical-align:top}}
th{{background:#edf4f4}}.handoff{{border:1px solid #b9d8d2;border-radius:12px;padding:16px;background:#edf9f6}}.flow{{display:flex;gap:0;overflow-x:auto;padding:18px 4px 8px}}.node{{min-width:170px;position:relative;padding-top:25px}}.node:before{{content:'';position:absolute;left:0;right:0;top:7px;height:2px;background:#b9d8d2}}.node:first-child:before{{left:50%}}.node:last-child:before{{right:50%}}.dot{{position:absolute;top:0;left:calc(50% - 8px);width:16px;height:16px;border-radius:50%;background:#178b7b;border:4px solid #dff4ef}}.card{{margin:0 6px;border:1px solid #d7e0e3;border-radius:10px;padding:10px;background:white;font-size:12px}}.feedback{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.feedback-card{{border:1px solid #d7e0e3;border-radius:10px;padding:0 14px;background:#f7faf9}}.feedback-card h3{{font-size:14px}}.feedback-card li{{margin:7px 0}}@media(max-width:700px){{.feedback{{grid-template-columns:1fr}}}}@media print{{body{{margin:0}}.flow{{overflow:visible}}}}
</style></head><body>
<h1>{html.escape(data['title'])}</h1>
<p><strong>Case:</strong> {html.escape(data['case_label'])}</p>
<h2>Handoff summary</h2><p class="handoff">{html.escape(data.get('handoff_summary', ''))}</p>
<h2>Timeline map</h2><div class="flow">{ReportService._html_graph(data['timeline'])}</div>
<h2>Chronological event log</h2><table><thead><tr><th>Time</th><th>Category</th><th>Event</th><th>Speaker</th><th>Transcript</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Session feedback</h2><div class="feedback">{feedback_html}</div>
</body></html>"""

    @staticmethod
    def _html_graph(timeline: list[dict[str, Any]]) -> str:
        return "".join(
            "<div class='node'><span class='dot'></span><div class='card'>"
            f"<strong>{html.escape(event['speech_time'])}</strong><br>"
            f"{html.escape(event['summary'])}<br>"
            f"<small>{html.escape(event.get('speaker', 'Unknown'))}</small>"
            "</div></div>"
            for event in timeline
        )

    @staticmethod
    def csv(report: ReportRecord) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "speech_time_ms",
                "speech_time",
                "category",
                "event",
                "speaker",
                "transcript",
            ]
        )
        for event in report.structured_json["timeline"]:
            writer.writerow(
                [
                    event["speech_time_ms"],
                    event["speech_time"],
                    event["category"],
                    event["summary"],
                    event.get("speaker", "Unknown"),
                    event["evidence"],
                ]
            )
        return output.getvalue()

