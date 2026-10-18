from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.db.database import Database
from app.services.pipeline import EvidencePipeline
from app.services.diarization import PyannoteDiarizer
from app.services.reporting import ReportService
from app.services.transcription import WhisperCppTranscriber


@lru_cache(maxsize=1)
def get_database() -> Database:
    database = Database(settings.db_path)
    database.initialize()
    return database


def get_pipeline() -> EvidencePipeline:
    return EvidencePipeline(get_database())


def get_report_service() -> ReportService:
    return ReportService(get_database())


@lru_cache(maxsize=1)
def get_transcriber() -> WhisperCppTranscriber:
    return WhisperCppTranscriber(settings)


@lru_cache(maxsize=1)
def get_diarizer() -> PyannoteDiarizer:
    return PyannoteDiarizer(settings)

