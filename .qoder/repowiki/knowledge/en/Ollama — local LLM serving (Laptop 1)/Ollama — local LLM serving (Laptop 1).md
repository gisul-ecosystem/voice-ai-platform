---
kind: external_dependency
name: Ollama — local LLM serving (Laptop 1)
slug: ollama
category: external_dependency
category_hints:
    - client_constraint
scope:
    - '**'
source_files:
    - README.md
    - services/voice-agent/clients/llm/
---

### Role
Default local LLM backend running Qwen3-4B on Laptop 1, exposed at `http://localhost:11434`. The voice-agent talks to it via the OpenAI-compatible `/v1/chat/completions` endpoint.

### Constraints
- Model tag is `qwen3:4b-instruct-2507-q8_0` (NOT `qwen3:4b-instruct-q8_0`).
- Hosted alternative is `https://llm.gisul.ai/v1` with model `qwen3:4b-instruct-2507-q4_K_M` — do NOT compare results between the two tags directly.
- Migration path: swap Ollama for vLLM on GPU servers with zero code changes (same OpenAI-compatible interface); vLLM uses `structured_outputs` instead of the deprecated `guided_json` parameter.