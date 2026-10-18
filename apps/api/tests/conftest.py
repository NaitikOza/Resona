from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
import app.api.websocket as websocket_routes
import app.dependencies as dependencies
from app.main import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    test_settings = replace(
        dependencies.settings,
        db_path=tmp_path / "resona-test.sqlite3",
        storage_path=tmp_path / "sessions",
        whisper_model_path=tmp_path / "missing-model.bin",
        pyannote_model_path=tmp_path / "missing-pyannote-model",
        keep_audio=True,
    )
    dependencies.get_database.cache_clear()
    dependencies.get_transcriber.cache_clear()
    dependencies.get_diarizer.cache_clear()
    monkeypatch.setattr(dependencies, "settings", test_settings)
    monkeypatch.setattr(routes, "settings", test_settings)
    monkeypatch.setattr(websocket_routes, "settings", test_settings)
    with TestClient(app) as test_client:
        yield test_client
    dependencies.get_database.cache_clear()
    dependencies.get_transcriber.cache_clear()
    dependencies.get_diarizer.cache_clear()

