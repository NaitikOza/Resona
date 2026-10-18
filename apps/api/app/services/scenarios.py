from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT


SCENARIO_DIR = REPO_ROOT / "scenarios/annotations"


def list_scenarios() -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenarios.append(
            {
                "slug": payload["slug"],
                "title": payload["title"],
                "description": payload["description"],
                "duration_ms": max(segment["end_ms"] for segment in payload["segments"]),
                "simulated": True,
            }
        )
    return scenarios


def load_scenario(slug: str) -> dict[str, Any]:
    if not slug.replace("-", "").isalnum():
        raise KeyError("Scenario not found")
    path = SCENARIO_DIR / f"{slug}.json"
    if not path.is_file():
        raise KeyError("Scenario not found")
    return json.loads(path.read_text(encoding="utf-8"))

