from app.services.transcription import WhisperCppTranscriber


def test_parse_json_omits_whisper_non_speech_markers() -> None:
    payload = {
        "transcription": [
            {
                "text": "[BLANK_AUDIO]",
                "timestamps": {"from": "00:00:00.000", "to": "00:00:01.000"},
            },
            {
                "text": "[silence]",
                "timestamps": {"from": "00:00:01.000", "to": "00:00:02.000"},
            },
            {
                "text": "Prepare two units of blood.",
                "timestamps": {"from": "00:00:02.000", "to": "00:00:03.000"},
            },
        ]
    }

    segments = WhisperCppTranscriber._parse_json(
        payload, offset_ms=4_000, asr_engine="whisper.cpp/base.en"
    )

    assert len(segments) == 1
    assert segments[0].raw_text == "Prepare two units of blood."
    assert segments[0].start_ms == 6_000
    assert segments[0].asr_engine == "whisper.cpp/base.en"


def test_parse_verbose_server_json_uses_audio_timestamps() -> None:
    payload = {
        "segments": [
            {
                "text": "IV is established.",
                "start": 1.2,
                "end": 2.4,
                "no_speech_prob": 0.02,
            }
        ]
    }

    segments = WhisperCppTranscriber._parse_json(
        payload, offset_ms=5_000, asr_engine="whisper.cpp/medium.en"
    )

    assert len(segments) == 1
    assert segments[0].start_ms == 6_200
    assert segments[0].end_ms == 7_400
    assert segments[0].raw_text == "IV is established."


def test_parse_verbose_server_json_splits_combined_sentences_by_word_time() -> None:
    payload = {
        "segments": [
            {
                "text": " Starting the IV now. IV is established.",
                "start": 0.8,
                "end": 3.9,
                "words": [
                    {"word": " Starting", "start": 0.8, "end": 1.3, "probability": 0.98},
                    {"word": " the", "start": 1.3, "end": 1.5, "probability": 0.99},
                    {"word": " IV", "start": 1.5, "end": 1.7, "probability": 0.99},
                    {"word": " now", "start": 1.7, "end": 2.0, "probability": 0.97},
                    {"word": ".", "start": 2.0, "end": 2.1, "probability": 0.9},
                    {"word": " IV", "start": 2.2, "end": 2.4, "probability": 0.98},
                    {"word": " is", "start": 2.4, "end": 2.6, "probability": 0.99},
                    {"word": " established", "start": 2.6, "end": 3.5, "probability": 0.99},
                    {"word": ".", "start": 3.5, "end": 3.9, "probability": 0.9},
                ],
            }
        ]
    }

    segments = WhisperCppTranscriber._parse_json(
        payload, offset_ms=3_000, asr_engine="whisper.cpp/medium.en"
    )

    assert [item.raw_text for item in segments] == [
        "Starting the IV now.",
        "IV is established.",
    ]
    assert [(item.start_ms, item.end_ms) for item in segments] == [
        (3_800, 5_100),
        (5_200, 6_900),
    ]


def test_parse_json_merges_adjacent_incomplete_sentence_segments() -> None:
    payload = {
        "segments": [
            {"text": "Did the blood", "start": 0.0, "end": 0.7},
            {"text": "arrive?", "start": 0.72, "end": 1.2},
        ]
    }

    segments = WhisperCppTranscriber._parse_json(
        payload, offset_ms=8_000, asr_engine="whisper.cpp/medium.en"
    )

    assert len(segments) == 1
    assert segments[0].raw_text == "Did the blood arrive?"
    assert segments[0].start_ms == 8_000
    assert segments[0].end_ms == 9_200


def test_parse_verbose_json_splits_distinct_actions_at_comma_boundary() -> None:
    payload = {
        "segments": [
            {
                "text": " IV is established, prepare two units of blood.",
                "start": 0.0,
                "end": 3.0,
                "words": [
                    {"word": " IV", "start": 0.0, "end": 0.3},
                    {"word": " is", "start": 0.3, "end": 0.5},
                    {"word": " established,", "start": 0.5, "end": 1.2},
                    {"word": " prepare", "start": 1.3, "end": 1.8},
                    {"word": " two", "start": 1.8, "end": 2.0},
                    {"word": " units", "start": 2.0, "end": 2.3},
                    {"word": " of", "start": 2.3, "end": 2.5},
                    {"word": " blood.", "start": 2.5, "end": 3.0},
                ],
            }
        ]
    }

    segments = WhisperCppTranscriber._parse_json(
        payload, offset_ms=0, asr_engine="whisper.cpp/medium.en"
    )

    assert [item.raw_text for item in segments] == [
        "IV is established.",
        "Prepare two units of blood.",
    ]
