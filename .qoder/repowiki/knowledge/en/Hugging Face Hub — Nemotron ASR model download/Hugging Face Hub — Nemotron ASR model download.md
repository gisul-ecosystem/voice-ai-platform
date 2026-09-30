---
kind: external_dependency
name: Hugging Face Hub — Nemotron ASR model download
slug: huggingface
category: external_dependency
category_hints:
    - client_constraint
scope:
    - '**'
source_files:
    - README.md
    - services/model-serving/stt/app.py
---

### Role
STT service downloads `nvidia/nemotron-3.5-asr-streaming-0.6b` from Hugging Face on first start. Requires CUDA GPU and CUDA-enabled PyTorch.

### Constraint
`torch`, `torchvision`, and `torchaudio` must be installed from the same CUDA index (`https://download.pytorch.org/whl/cu124`); mismatched torchvision raises `RuntimeError: operator torchvision::nms does not exist`.