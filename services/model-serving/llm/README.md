# LLM node (Laptop 1)

Runs Qwen3-4B-Instruct via Ollama, quantized to Q8 (near-lossless quality,
fits comfortably in 8GB VRAM on an RTX 4060 laptop).

Why Ollama and not vLLM here: vLLM claims VRAM aggressively and is built for
server-class GPUs -- on an 8GB laptop card, Ollama/llama.cpp-based serving is
the practical choice. Ollama exposes the same OpenAI-compatible
`/v1/chat/completions` API vLLM does, so switching to vLLM later (on a real
GPU server) is a `.env` URL change in `voice-agent`, not a code change.

## Run
```bash
./run_ollama.sh
```

## When you get a GPU server instead
```bash
vllm serve Qwen/Qwen3-4B-Instruct-2507 \
  --quantization awq \
  --gpu-memory-utilization 0.85 \
  --port 8000
```
Update `LLM_SERVICE_URL` in `voice-agent/.env` accordingly. No other changes needed.
