"""
Laptop 2 -- STT node
FastAPI wrapper around Nemotron 3.5 ASR 0.6B (NeMo).
Exposes POST /transcribe accepting an audio file, returns text.
"""
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import tempfile
import os

app = FastAPI(title="STT Service - Nemotron 3.5 ASR")

# Loaded once at startup, not per-request
_asr_model = None


@app.on_event("startup")
def load_model():
    global _asr_model
    import nemo.collections.asr as nemo_asr
    _asr_model = nemo_asr.models.ASRModel.from_pretrained(
        model_name="nvidia/nemotron-3.5-asr-streaming-0.6b"
    )


@app.get("/health")
def health():
    return {"status": "ok", "model": "nemotron-3.5-asr-0.6b", "loaded": _asr_model is not None}


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[-1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        # target_lang is required -- without it, Nemotron 3.5 ASR raises
        # "ValueError: Unknown prompt key: 'None'". "auto" enables
        # automatic language detection; pin to "en-US" if you want to force
        # English and skip detection overhead.
        result = _asr_model.transcribe([tmp_path], target_lang="auto")
        text = result[0].text if hasattr(result[0], "text") else str(result[0])
        return JSONResponse({"text": text})
    finally:
        os.unlink(tmp_path)
