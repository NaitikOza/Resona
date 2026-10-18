from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
load_dotenv(API_DIR / ".env")


def _resolve_path(value: str, default: Path) -> Path:
    candidate = Path(value).expanduser() if value else default
    return candidate if candidate.is_absolute() else (API_DIR / candidate).resolve()


@dataclass(frozen=True)
class Settings:
    db_path: Path
    storage_path: Path
    whisper_binary_path: str
    whisper_model_path: Path
    whisper_server_url: str | None
    whisper_threads: int
    audio_window_seconds: int
    keep_audio: bool
    enable_local_llm: bool
    pyannote_model_path: Path
    diarization_min_speakers: int
    diarization_max_speakers: int

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            db_path=_resolve_path(
                os.getenv("RESONA_DB_PATH", ""), REPO_ROOT / "local_data/resona.sqlite3"
            ),
            storage_path=_resolve_path(
                os.getenv("RESONA_STORAGE_PATH", ""), REPO_ROOT / "local_data/sessions"
            ),
            whisper_binary_path=os.getenv("WHISPER_BINARY_PATH", "whisper-cli"),
            whisper_model_path=_resolve_path(
                os.getenv("WHISPER_MODEL_PATH", ""),
                REPO_ROOT / "local_data/models/ggml-medium.en.bin",
            ),
            whisper_server_url=os.getenv("WHISPER_SERVER_URL") or None,
            whisper_threads=max(1, int(os.getenv("WHISPER_THREADS", "4"))),
            audio_window_seconds=max(
                2, min(30, int(os.getenv("RESONA_AUDIO_WINDOW_SECONDS", "4")))
            ),
            keep_audio=os.getenv("RESONA_KEEP_AUDIO", "true").lower() == "true",
            enable_local_llm=os.getenv("ENABLE_LOCAL_LLM", "false").lower() == "true",
            pyannote_model_path=_resolve_path(
                os.getenv("PYANNOTE_MODEL_PATH", ""),
                REPO_ROOT
                / "local_data/models/pyannote-speaker-diarization-community-1",
            ),
            diarization_min_speakers=max(
                1, int(os.getenv("RESONA_DIARIZATION_MIN_SPEAKERS", "1"))
            ),
            diarization_max_speakers=max(
                1, int(os.getenv("RESONA_DIARIZATION_MAX_SPEAKERS", "8"))
            ),
        )


settings = Settings.from_environment()

