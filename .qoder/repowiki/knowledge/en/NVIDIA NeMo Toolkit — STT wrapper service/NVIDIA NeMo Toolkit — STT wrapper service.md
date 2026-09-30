---
kind: external_dependency
name: NVIDIA NeMo Toolkit — STT wrapper service
slug: nemotoolkit
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
source_files:
    - services/model-serving/stt/requirements.txt
    - services/model-serving/stt/app.py
---

### Role
FastAPI wrapper around NVIDIA NeMo's ASR pipeline (`nemo_toolkit[asr]`) exposing a simple transcribe endpoint on Laptop 2 (`:5552`). The wrapper adds required `target_lang` handling (defaults to `auto`).

### Dependency constraint
Must be installed AFTER installing matching CUDA wheels for torch/torchvision/torchaudio from the cu124 index.