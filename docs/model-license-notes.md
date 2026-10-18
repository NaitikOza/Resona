# Local model and license notes

Resona's required inference path is free, local, and usable without an account or API key.

| Component | Used by default | Size on disk | License / source | Notes |
|---|---:|---:|---|---|
| `whisper.cpp` | Yes | Homebrew/build dependent | [MIT](https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE) | Local CLI inference. Resona was verified with `whisper.cpp` 1.9.5. |
| Whisper `medium.en` GGML | Yes after setup | ~1.5 GiB | [Model card/source](https://huggingface.co/ggerganov/whisper.cpp/tree/main) | Default English model; setup verifies SHA-1 `8c30f0e44ce9560643ebd10bbe50cd20eafd3723`. |
| Whisper `small.en` GGML | Optional | ~466 MiB | [Model card/source](https://huggingface.co/ggerganov/whisper.cpp/tree/main) | Lower-memory fallback; setup verifies SHA-1 `db8a495a91d927739e50b3fc1cc4c6b8f6c2d022`. |
| Whisper `base.en` GGML | Optional | ~142 MiB | [Model card/source](https://huggingface.co/ggerganov/whisper.cpp/tree/main) | Lower-memory fallback; setup verifies SHA-1 `137c40403d78fd54d454da0f9bd998f78703390c`. |
| Whisper `tiny.en` GGML | Optional | ~75 MiB | [Model card/source](https://huggingface.co/ggerganov/whisper.cpp/tree/main) | Lower-storage alternative; setup verifies SHA-1 `c78c86eb1a8faa21b369bcd33207cc90d64ae9df`. |
| `pyannote.audio` | Yes | ~1 GiB Python environment with PyTorch dependencies | [MIT](https://github.com/pyannote/pyannote-audio/blob/main/LICENSE) | Local speaker-diarization runtime; audio is passed from memory and is not uploaded. |
| pyannote Community-1 | After speaker setup | Download size varies by upstream revision | [CC-BY-4.0 model card](https://huggingface.co/pyannote/speaker-diarization-community-1) | Free and locally runnable. Initial access requires accepting the publisher's conditions and using a free Hugging Face token. |
| Deterministic extraction rules | Yes | Negligible | Project source | Authoritative default event pipeline; no model weights. |
| Qwen2.5-1.5B-Instruct GGUF | No | ~1.12 GiB for Q4_K_M | [Apache-2.0 model repository](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) | Feasible optional future helper through `llama.cpp`; not downloaded, connected, or required. |
| `llama.cpp` | No | Build dependent | [MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) | Optional runtime only. The `ENABLE_LOCAL_LLM` flag remains false and cannot change the core behavior. |

Whisper, pyannote weights, and generated/local audio are intentionally excluded from Git. The speaker setup script reads the Hugging Face token only from the current process environment and saves Community-1 under ignored local storage. No hosted inference service is used.

Major application frameworks are open source: [Next.js](https://github.com/vercel/next.js/blob/canary/license.md) (MIT), [React](https://github.com/facebook/react/blob/main/LICENSE) (MIT), [FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE) (MIT), and [SQLite](https://www.sqlite.org/copyright.html) (public domain). Exact transitive package versions are pinned in `pnpm-lock.yaml` and `apps/api/uv.lock`.

Licenses and model terms should be reviewed again before redistribution or production use. No claim in this document grants rights beyond the upstream licenses.
