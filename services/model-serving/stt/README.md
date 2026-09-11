# STT node (Laptop 2)

Nemotron 3.5 ASR 0.6B, ~2-3GB VRAM, comfortable fit on 8GB laptop GPU.

Install matching CUDA PyTorch wheels first (`torch` + `torchvision` + `torchaudio` from the same index), then `pip install -r requirements.txt`. A mismatched `torchvision` fails startup with `RuntimeError: operator torchvision::nms does not exist`.

Run: `python -m uvicorn app:app --host 0.0.0.0 --port 8001`
Test: `curl -F "file=@sample.wav" http://localhost:8001/transcribe`
