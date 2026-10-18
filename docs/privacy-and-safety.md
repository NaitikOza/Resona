# Privacy and safety

Resona is a local trauma documentation application. It is not a medical device, a clinical decision-support system, or a replacement for clinician review.

## Data boundary

Audio, transcripts, events, reviews, and reports remain on the development computer. The browser connects only to the loopback Next.js and FastAPI services. Resona contains no analytics, telemetry, cloud transcription, remote inference, CDN dependency, or paid API integration.

Do not use Resona with real patients or real emergencies. Only record a staged exercise after every participant has consented. Do not enter names, dates of birth, record numbers, contact details, or other identifying information.

Browser microphone permission is requested only when the user starts a device test or live recording. A visible recording state, timer, pause control, finish control, and delete action remain available during capture.

## Local storage

By default Resona stores:

- the SQLite database at `local_data/resona.sqlite3`;
- retained uploads and live PCM under `local_data/sessions/<session-id>/`;
- manually downloaded Whisper weights under `local_data/models/`.

All of `local_data/` except its placeholder is ignored by Git. Common audio, model-weight, SQLite, environment, and generated-report extensions are also ignored. The session **Discard** action deletes its database rows and associated session directory. Set `RESONA_KEEP_AUDIO=false` to remove uploaded audio after transcription; live audio chunks are then not persisted either.

The database is not encrypted and the app has no authentication. Keep both services bound to `127.0.0.1`, use only synthetic data, restrict workstation access, and delete sessions after a demonstration.

## Evidence policy

Every extracted event has:

- source segment identifiers;
- an exact evidence quote;
- a source-relative utterance timestamp;
- a state and explicit uncertainty/review status;
- a human-review status and audit trail.

The database rejects extracted evidence that is not present verbatim in the cited transcript. A request, plan, question, preparation step, or acknowledged instruction is never promoted to `COMPLETED`. Blood preparation and blood availability are never treated as administration. Missing confirmations, ambiguous doses, conflicts, and uncertain text create review items or uncertain events. Numeric ASR confidence is not shown as though it were a clinical assurance score.

Reviewers can correct transcript display text, accept/edit/reject events, add manual events, and record a change reason. The original raw transcript and audit entries remain preserved. Generated reports label unknowns as **not stated** and include a visible “NOT A MEDICAL RECORD” warning.

## Threat model and non-goals

The application protects against accidental cloud transmission and unsupported completion inference in its intended single-user local setup. It does not protect against a compromised workstation, another local user with filesystem access, malicious local software, or physical access. It has not undergone clinical validation, security certification, accessibility certification, penetration testing, or regulatory review.

If the app is ever extended beyond a local simulation, it needs formal threat modeling, authentication, authorization, encryption, retention controls, consent governance, audit export, accessibility testing, clinical validation, and appropriate legal/regulatory review before any use with health information.
