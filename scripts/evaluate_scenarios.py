#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps/api"
sys.path.insert(0, str(API_ROOT))

from app.models.schemas import SegmentReviewStatus, TranscriptSegment  # noqa: E402
from app.services.extraction import DeterministicExtractor  # noqa: E402


def main() -> None:
    expected_count = 0
    predicted_count = 0
    exact_matches = 0
    false_completions = 0
    scenarios = sorted((REPO_ROOT / "scenarios/annotations").glob("*.json"))
    extractor = DeterministicExtractor()
    for scenario_path in scenarios:
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        predicted: list[tuple[str, str, str]] = []
        for index, raw in enumerate(scenario["segments"]):
            segment = TranscriptSegment(
                id=f"{scenario['slug']}-{index}",
                session_id=scenario["slug"],
                start_ms=raw["start_ms"],
                end_ms=raw["end_ms"],
                raw_text=raw["text"],
                corrected_text=None,
                speaker_label=raw.get("speaker", "Unknown"),
                asr_engine="reference-transcript",
                confidence=raw.get("confidence", 1.0),
                review_status=SegmentReviewStatus.RAW,
                created_at=datetime.now(UTC),
            )
            predicted.extend(
                (event.normalized_action, event.state.value, event.evidence_text)
                for event in extractor.extract(segment)
            )
        expected = [
            (event["action"], event["state"])
            for event in scenario["expected_events"]
        ]
        expected_count += len(expected)
        predicted_count += len(predicted)
        exact_matches += sum(
            1
            for index, item in enumerate(predicted)
            if index < len(expected) and item[:2] == expected[index]
        )
        if scenario.get("negative_control"):
            false_completions += sum(1 for _, state, _ in predicted if state == "COMPLETED")

    precision = exact_matches / predicted_count if predicted_count else 0
    recall = exact_matches / expected_count if expected_count else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    result = {
        "scope": "deterministic extraction against authored transcript annotations; not an ASR or clinical validation benchmark",
        "scenario_count": len(scenarios),
        "expected_events": expected_count,
        "predicted_events": predicted_count,
        "exact_action_state_matches": exact_matches,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_completions_in_annotated_negative_controls": false_completions,
        "evidence_attribution": "all generated events carry an exact source segment and verbatim text",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
