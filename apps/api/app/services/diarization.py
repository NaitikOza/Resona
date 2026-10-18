from __future__ import annotations

import asyncio
import gc
import importlib.util
import os
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.schemas import DiarizationStatus, TranscriptSegment


class DiarizationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeakerTurn:
    start_ms: int
    end_ms: int
    speaker: str


class PyannoteDiarizer:
    """Run the downloaded pyannote Community-1 model entirely on this device."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> DiarizationStatus:
        package_ready = importlib.util.find_spec("pyannote.audio") is not None
        model_ready = (self.settings.pyannote_model_path / "config.yaml").is_file()
        if not package_ready:
            detail = "Speaker detection dependency is not installed."
        elif not model_ready:
            detail = "Speaker detection model is not installed."
        else:
            detail = "Speaker detection is ready."
        return DiarizationStatus(
            available=package_ready and model_ready,
            model_path=str(self.settings.pyannote_model_path) if model_ready else None,
            detail=detail,
        )

    async def diarize(self, audio_path: Path) -> list[SpeakerTurn]:
        status = self.status()
        if not status.available:
            raise DiarizationUnavailable(status.detail)
        return await asyncio.to_thread(self._run, audio_path)

    def _run(self, audio_path: Path) -> list[SpeakerTurn]:
        os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        import numpy as np
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(str(self.settings.pyannote_model_path))
        try:
            samples, sample_rate = _read_audio(audio_path, np)
            waveform = torch.from_numpy(samples).unsqueeze(0)
            output = pipeline(
                {"waveform": waveform, "sample_rate": sample_rate},
                min_speakers=self.settings.diarization_min_speakers,
                max_speakers=max(
                    self.settings.diarization_min_speakers,
                    self.settings.diarization_max_speakers,
                ),
            )
            annotation = getattr(output, "exclusive_speaker_diarization", None)
            if annotation is None:
                annotation = getattr(output, "speaker_diarization", output)
            return _annotation_turns(annotation)
        finally:
            del pipeline
            gc.collect()
            if hasattr(torch, "mps") and torch.backends.mps.is_available():
                torch.mps.empty_cache()


def assign_speakers(
    segments: list[TranscriptSegment], turns: list[SpeakerTurn]
) -> dict[str, str]:
    if not segments:
        return {}
    speaker_order: dict[str, str] = {}
    assignments: dict[str, str] = {}
    for segment in segments:
        overlaps: dict[str, int] = {}
        for turn in turns:
            overlap = max(
                0,
                min(segment.end_ms, turn.end_ms)
                - max(segment.start_ms, turn.start_ms),
            )
            if overlap:
                overlaps[turn.speaker] = overlaps.get(turn.speaker, 0) + overlap
        if not overlaps:
            continue
        raw_speaker = max(overlaps, key=overlaps.get)
        if raw_speaker not in speaker_order:
            speaker_order[raw_speaker] = f"Speaker {len(speaker_order) + 1}"
        assignments[segment.id] = speaker_order[raw_speaker]
    return infer_speaker_roles(segments, assignments)


def infer_speaker_roles(
    segments: list[TranscriptSegment], assignments: dict[str, str]
) -> dict[str, str]:
    role_by_label: dict[str, str] = {}
    role_by_segment: dict[str, str] = {}
    ordered = sorted(segments, key=lambda item: item.start_ms)
    role_prefix = re.compile(
        r"^\s*(?:okay\s+)?"
        r"(doctor|physician|nurse|paramedic|patient|respiratory therapist|team leader)"
        r"\s*[,;:\-]",
        re.IGNORECASE,
    )
    self_identification = re.compile(
        r"\b(?:i am|i'm|this is)\s+(?:the\s+)?"
        r"(paramedic|doctor|physician|nurse|patient|respiratory therapist)\b",
        re.IGNORECASE,
    )
    for segment in ordered:
        text = segment.corrected_text or segment.raw_text
        prefix_match = role_prefix.search(text)
        if prefix_match:
            explicit_role = prefix_match.group(1).title()
            role_by_segment[segment.id] = (
                "Doctor" if explicit_role == "Physician" else explicit_role
            )
        label = assignments.get(segment.id)
        if not label:
            continue
        match = self_identification.search(text)
        if match:
            identified_role = match.group(1).title()
            role_by_label[label] = (
                "Doctor" if identified_role == "Physician" else identified_role
            )

    for index, segment in enumerate(ordered):
        text = segment.corrected_text or segment.raw_text
        if not re.search(r"\bparamedics?\b.*\b(?:give|report)\b", text, re.IGNORECASE):
            continue
        source_label = assignments.get(segment.id)
        for response in ordered[index + 1 :]:
            if response.start_ms - segment.end_ms > 15_000:
                break
            response_label = assignments.get(response.id)
            if response_label and response_label != source_label:
                role_by_label.setdefault(response_label, "Paramedic")
                break

    resolved = {
        segment_id: role_by_segment.get(segment_id, role_by_label.get(label, label))
        for segment_id, label in assignments.items()
    }
    resolved.update(role_by_segment)
    return resolved


def _read_audio(audio_path: Path, np: Any) -> tuple[Any, int]:
    if audio_path.suffix.lower() == ".wav":
        with wave.open(str(audio_path), "rb") as source:
            if source.getsampwidth() != 2:
                raise ValueError("Speaker detection requires 16-bit PCM audio")
            sample_rate = source.getframerate()
            channels = source.getnchannels()
            samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")
            if channels > 1:
                samples = samples.reshape(-1, channels).mean(axis=1)
    else:
        sample_rate = 16_000
        samples = np.fromfile(audio_path, dtype="<i2")
    return samples.astype("float32") / 32768.0, sample_rate


def _annotation_turns(annotation: Any) -> list[SpeakerTurn]:
    turns: list[SpeakerTurn] = []
    if hasattr(annotation, "itertracks"):
        iterator = (
            (turn, speaker)
            for turn, _, speaker in annotation.itertracks(yield_label=True)
        )
    else:
        iterator = iter(annotation)
    for turn, speaker in iterator:
        start_ms = max(0, round(float(turn.start) * 1000))
        end_ms = max(start_ms + 1, round(float(turn.end) * 1000))
        turns.append(SpeakerTurn(start_ms, end_ms, str(speaker)))
    return turns
