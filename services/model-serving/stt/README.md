# STT node (Laptop 2)

Nemotron 3.5 ASR 0.6B, ~2-3GB VRAM, comfortable fit on 8GB laptop GPU.

Run: `uvicorn app:app --host 0.0.0.0 --port 8001`
Test: `curl -F "file=@sample.wav" http://localhost:8001/transcribe`
