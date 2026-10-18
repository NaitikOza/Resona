from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.models.schemas import ModelStatus, TranscriptSegmentCreate


class TranscriptionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PcmWindow:
    pcm16: bytes
    start_ms: int
    end_ms: int


class WhisperCppTranscriber:
    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self) -> ModelStatus:
        binary = self._binary()
        if binary is None:
            return ModelStatus(
                available=False,
                engine="whisper.cpp",
                detail=(
                    "whisper-cli was not found. Install whisper.cpp and set "
                    "WHISPER_BINARY_PATH. The sample scenario and deterministic "
                    "documentation workflow remain available."
                ),
            )
        if not self.settings.whisper_model_path.is_file():
            return ModelStatus(
                available=False,
                engine="whisper.cpp",
                model_path=str(self.settings.whisper_model_path),
                detail="The configured local Whisper model is missing. Run scripts/setup_whisper.sh.",
            )
        return ModelStatus(
            available=True,
            engine="whisper.cpp",
            model_path=str(self.settings.whisper_model_path),
            detail=(
                f"Local whisper.cpp model {self.settings.whisper_model_path.name} "
                "is ready."
            ),
        )

    def _binary(self) -> str | None:
        configured = Path(self.settings.whisper_binary_path).expanduser()
        if configured.is_file():
            return str(configured.resolve())
        return shutil.which(self.settings.whisper_binary_path)

    async def transcribe_pcm(self, window: PcmWindow) -> list[TranscriptSegmentCreate]:
        with tempfile.TemporaryDirectory(prefix="resona-asr-") as temp_dir:
            wav_path = Path(temp_dir) / "window.wav"
            write_pcm16_wav(wav_path, window.pcm16)
            return await self.transcribe_wav(wav_path, offset_ms=window.start_ms)

    async def transcribe_wav(
        self, wav_path: Path, offset_ms: int = 0
    ) -> list[TranscriptSegmentCreate]:
        status = self.status()
        if not status.available:
            raise TranscriptionUnavailable(status.detail)
        try:
            validate_wav(wav_path)
        except (ValueError, wave.Error) as error:
            raise ValueError(
                "Audio must be a mono 16 kHz, 16-bit PCM WAV file. "
                "Convert locally before upload; compressed audio is never sent to a cloud service."
            ) from error
        if self.settings.whisper_server_url:
            try:
                return await self._run_server(wav_path, offset_ms)
            except (httpx.HTTPError, json.JSONDecodeError, ValueError):
                # Keep recording functional if the resident process is still
                # starting or exits unexpectedly.
                pass
        return await asyncio.to_thread(self._run_cli, wav_path, offset_ms)

    async def _run_server(
        self, wav_path: Path, offset_ms: int
    ) -> list[TranscriptSegmentCreate]:
        endpoint = f"{self.settings.whisper_server_url.rstrip('/')}/inference"
        timeout = httpx.Timeout(180.0, connect=0.5)
        with wav_path.open("rb") as audio:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint,
                    data={"response_format": "verbose_json"},
                    files={"file": (wav_path.name, audio, "audio/wav")},
                )
        response.raise_for_status()
        payload = response.json()
        return self._parse_json(
            payload,
            offset_ms,
            f"whisper.cpp/{self._model_name()}",
        )

    def _run_cli(self, wav_path: Path, offset_ms: int) -> list[TranscriptSegmentCreate]:
        binary = self._binary()
        if binary is None:
            raise TranscriptionUnavailable("whisper-cli is unavailable")
        with tempfile.TemporaryDirectory(prefix="resona-whisper-output-") as temp_dir:
            output_base = Path(temp_dir) / "transcript"
            command = [
                binary,
                "-m",
                str(self.settings.whisper_model_path),
                "-f",
                str(wav_path),
                "-l",
                "en",
                "-t",
                str(self.settings.whisper_threads),
                "-oj",
                "-of",
                str(output_base),
                "--suppress-nst",
                "-np",
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            json_path = output_base.with_suffix(".json")
            if result.returncode != 0 or not json_path.is_file():
                detail = (result.stderr or result.stdout or "Unknown whisper.cpp error").strip()
                raise RuntimeError(f"Local transcription failed: {detail[-1200:]}")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            return self._parse_json(
                payload,
                offset_ms,
                f"whisper.cpp/{self._model_name()}",
            )

    def _model_name(self) -> str:
        return (
            self.settings.whisper_model_path.name.removeprefix("ggml-")
            .removesuffix(".bin")
        )

    @staticmethod
    def _parse_json(
        payload: dict[str, Any], offset_ms: int, asr_engine: str
    ) -> list[TranscriptSegmentCreate]:
        source_segments = payload.get("transcription") or payload.get("segments") or []
        raw_segments = [
            piece
            for raw in source_segments
            for piece in _sentence_pieces(raw)
        ]
        segments: list[TranscriptSegmentCreate] = []
        for index, raw in enumerate(raw_segments):
            text = str(raw.get("text", "")).strip()
            if not text or _is_non_speech_marker(text):
                continue
            timestamps = raw.get("timestamps") or {}
            start = _timestamp_ms(timestamps.get("from") or raw.get("start"), index * 1000)
            end = _timestamp_ms(timestamps.get("to") or raw.get("end"), start + 1000)
            probability = raw.get("confidence")
            if probability is None:
                probability = max(0.0, min(1.0, 1.0 - float(raw.get("no_speech_prob", 0.12))))
            segments.append(
                TranscriptSegmentCreate(
                    start_ms=offset_ms + start,
                    end_ms=offset_ms + max(start + 1, end),
                    raw_text=text,
                    speaker_label="Unknown",
                    asr_engine=asr_engine,
                    confidence=float(probability),
                )
            )
        return _merge_incomplete_segments(segments)


def _sentence_pieces(raw: dict[str, Any]) -> list[dict[str, Any]]:
    words = raw.get("words")
    if not isinstance(words, list) or not words:
        return [raw]
    valid_words = [
        word
        for word in words
        if isinstance(word, dict) and str(word.get("word", "")).strip()
    ]
    pieces: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for index, word in enumerate(valid_words):
        current.append(word)
        token = str(word["word"]).strip()
        next_token = (
            re.sub(r"[^a-z]+", "", str(valid_words[index + 1]["word"]).casefold())
            if index + 1 < len(valid_words)
            else ""
        )
        terminal = bool(re.search(r"[.!?][\"')\]]?$", token))
        clause_break = bool(re.search(r",[\"')\]]?$", token)) and next_token in {
            "administer",
            "can",
            "did",
            "give",
            "get",
            "prepare",
            "start",
            "starting",
        }
        if terminal or clause_break:
            piece = _words_to_piece(current, raw)
            if clause_break:
                piece["text"] = str(piece["text"]).rstrip().rstrip(",") + "."
            pieces.append(piece)
            current = []
    if current:
        pieces.append(_words_to_piece(current, raw))
    return pieces or [raw]


def _merge_incomplete_segments(
    segments: list[TranscriptSegmentCreate],
) -> list[TranscriptSegmentCreate]:
    merged: list[TranscriptSegmentCreate] = []
    for segment in segments:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and not re.search(r"[.!?][\"')\]]?$", previous.raw_text.strip())
            and 0 <= segment.start_ms - previous.end_ms <= 750
            and segment.asr_engine == previous.asr_engine
        ):
            merged[-1] = TranscriptSegmentCreate(
                start_ms=previous.start_ms,
                end_ms=segment.end_ms,
                raw_text=f"{previous.raw_text.rstrip()} {segment.raw_text.lstrip()}",
                speaker_label=previous.speaker_label,
                asr_engine=previous.asr_engine,
                confidence=(previous.confidence + segment.confidence) / 2,
            )
        else:
            merged.append(segment)
    return merged


def _words_to_piece(words: list[dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    probabilities = [
        float(word["probability"])
        for word in words
        if isinstance(word.get("probability"), (int, float))
    ]
    text = "".join(str(word["word"]) for word in words).strip()
    first_letter = re.search(r"[a-z]", text, re.IGNORECASE)
    if first_letter:
        position = first_letter.start()
        text = text[:position] + text[position].upper() + text[position + 1 :]
    return {
        "text": text,
        "start": words[0].get("start", raw.get("start")),
        "end": words[-1].get("end", raw.get("end")),
        "confidence": sum(probabilities) / len(probabilities) if probabilities else None,
        "no_speech_prob": raw.get("no_speech_prob", 0.12),
    }


def _is_non_speech_marker(text: str) -> bool:
    normalized = re.sub(r"[^a-z]+", " ", text.casefold()).strip()
    return normalized in {
        "blank audio",
        "silence",
        "music",
        "applause",
        "inaudible",
        "no speech",
    }


def _timestamp_ms(value: Any, fallback: int) -> int:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number * 1000) if number < 1000 else int(number)
    text = str(value).strip().replace(",", ".")
    if ":" not in text:
        try:
            number = float(text)
            return int(number * 1000) if number < 1000 else int(number)
        except ValueError:
            return fallback
    try:
        parts = [float(part) for part in text.split(":")]
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return int(seconds * 1000)
    except ValueError:
        return fallback


def write_pcm16_wav(path: Path, pcm16: bytes, sample_rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm16)


def validate_wav(path: Path) -> None:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1:
            raise ValueError("WAV must be mono")
        if source.getsampwidth() != 2:
            raise ValueError("WAV must be 16-bit PCM")
        if source.getframerate() != 16_000:
            raise ValueError("WAV must use a 16 kHz sample rate")

