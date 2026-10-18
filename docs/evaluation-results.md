# Evaluation results

Measured on October 17, 2026 on an Apple M2 development machine with 8 GB RAM, macOS 15.2 arm64, Node.js 20.16, Python 3.12, and `whisper.cpp` 1.9.5. The default English `medium.en` GGML model occupies about 1.5 GiB.

## Deterministic extraction cases

Command:

```bash
uv run --directory apps/api python ../../scripts/evaluate_scenarios.py
```

| Measure | Result |
|---|---:|
| Sample cases | 8 |
| Independently authored expected events | 18 |
| Predicted events | 18 |
| Exact normalized-action + state matches | 18 |
| Precision | 1.000 |
| Recall | 1.000 |
| F1 | 1.000 |
| False completion on explicit negative controls | 0 |

These are targeted, repository-authored regression cases. They validate the intended rule semantics—including request-versus-completion, cancellation, negation, ambiguity, abbreviations, and blood-preparation controls—but do not estimate general clinical performance.

## Local prerecorded transcription

The local demo generator produced a 9.843-second, mono 16 kHz PCM16 WAV containing synthesized speech. `medium.en` transcribed it in 5.59 seconds with a 2.14 GB peak memory footprint and produced six clean sentence-level transcript segments and six extracted events:

- reported blood pressure;
- IV access requested;
- IV access in progress;
- IV access explicitly completed;
- blood preparation requested;
- blood availability question captured.

A direct `whisper-cli` run completed in 5.59 seconds with a peak process footprint of roughly 2.14 GB. Timing will vary with power state, build flags, model choice, and audio.

## Live transport validation

Command, with the API already running:

```bash
uv run --directory apps/api python ../../scripts/validate_live_stream.py \
  ../../local_data/demo/synthetic-trauma-demo.wav
```

The validator sent browser-format binary frames over the live WebSocket and observed:

| Signal | Observed |
|---|---:|
| Sequenced frame acknowledgements | 39 |
| ASR processing windows | 3 |
| Final transcript messages | 6 |
| Event-added messages | 6 |
| Explicit IV completion retained | Yes |

The resident transcription server processed the complete 9.843-second sample in 2.29 seconds without reloading the model; a five-second window took 1.79 seconds. Live capture uses five-second windows with two seconds of overlap so updates continue while the user speaks and utterances at window boundaries are retained. Boundary phrases are split using word timestamps, clipped edges are deferred, and repeated overlap is removed before events are extracted. The validator retained all six expected sentences without clipped duplicates. It deletes its temporary session when it exits.

Automated Chromium QA verified that microphone permission appears only after an explicit user action, a system microphone can be selected and opened, AudioWorklet frames reach the UI, speech appears before Finish is pressed, pause/resume/finish/delete controls work, the live level meter updates, and the final partial audio buffer is flushed. The microphone test verifies all six expected sentences without clipped boundary phrases. An ordinary MP3 completed the browser decode, resample, upload, and transcription flow in under five seconds.

## Application tests

The release verification passed:

- 43 FastAPI/database/extraction/report/transcription/diarization tests;
- 7 Vitest component and utility tests;
- 1 Playwright sample-to-report browser test;
- 1 Playwright local-AI microphone-to-completed-event browser test;
- 1 Playwright MP3-upload-to-transcript browser test;
- TypeScript type checking;
- ESLint;
- optimized Next.js production build.

The browser flow loaded a sample case, reviewed an event, generated a report, and downloaded JSON. Desktop and 390-pixel mobile layouts were visually inspected.

The pyannote 4.0.7 runtime and its local PyTorch dependencies import successfully. Automated tests verify largest-overlap timestamp alignment, stable neutral speaker numbering, explicit self-identification, and report-handoff role anchoring. The Community-1 weights were not available in the test environment because the publisher requires account acceptance and a download token, so a real multi-speaker diarization accuracy run remains pending.

## Remaining validation boundary

Resona has not been evaluated on real clinical audio, protected health information, multiple simultaneous speakers, accents, background alarms, or large independent datasets. Speaker separation is a review aid, not verified identity, and overlapping speech can still be mislabeled. A live spoken-microphone run by the presenter should be included in the venue sound check; the prerecorded and curated paths remain available if room acoustics or browser permissions are unreliable.
