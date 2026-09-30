---
kind: external_dependency
name: Kokoro — local TTS model (Laptop 3)
slug: kokoro
category: external_dependency
category_hints:
    - client_constraint
scope:
    - '**'
source_files:
    - README.md
    - services/model-serving/tts/requirements.txt
---

### Role
Default TTS model wrapped in a FastAPI service on Laptop 3 (`:5553`). Uses the `kokoro` Python package plus `soundfile` and Redis.

### Constraints
- OS dependency: `espeak-ng` must be installed.
- Default voice is American English `af_heart`; no native Indian-accented English (`hf_*` is Hindi, a different language).
- CosyVoice 2 is unimplemented until built and tested.