#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO_ROOT / "local_data/models/pyannote-speaker-diarization-community-1"


def main() -> None:
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        raise SystemExit(
            "Set HF_TOKEN after accepting the pyannote Community-1 model terms. "
            "The token is used only for the initial local download."
        )
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="pyannote/speaker-diarization-community-1",
        local_dir=MODEL_DIR,
        token=token,
    )
    print(f"Speaker detection model saved to {MODEL_DIR}")


if __name__ == "__main__":
    main()
