"""
Laptop 2 -- STT node
FastAPI wrapper around Nemotron 3.5 ASR 0.6B (NeMo).
Exposes POST /transcribe accepting an audio file, returns text.
"""
from __future__ import annotations

import logging
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger("stt")
logging.basicConfig(level=logging.INFO)

# NeMo's transcribe() uses tempfile.TemporaryDirectory() for a manifest.
# On Windows the dataloader still holds manifest.json when the context
# exits (WinError 32), so cleanup raises even after a successful decode.
if sys.platform == "win32":
    _TemporaryDirectory = tempfile.TemporaryDirectory

    class _WindowsTemporaryDirectory(_TemporaryDirectory):
        def __init__(self, *args, **kwargs):
            kwargs["ignore_cleanup_errors"] = True
            super().__init__(*args, **kwargs)

    tempfile.TemporaryDirectory = _WindowsTemporaryDirectory  # type: ignore[misc]

app = FastAPI(title="STT Service - Nemotron 3.5 ASR")

_asr_model = None


@app.on_event("startup")
def load_model() -> None:
    global _asr_model
    import nemo.collections.asr as nemo_asr

    _asr_model = nemo_asr.models.ASRModel.from_pretrained(
        model_name="nvidia/nemotron-3.5-asr-streaming-0.6b"
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": "nemotron-3.5-asr-0.6b", "loaded": _asr_model is not None}


def _run_transcribe(wav_path: str):
    # target_lang is required -- without it, Nemotron 3.5 ASR raises
    # "ValueError: Unknown prompt key: 'None'".
    try:
        return _asr_model.transcribe(
            [wav_path],
            target_lang="auto",
            num_workers=0,
        )
    except TypeError:
        return _asr_model.transcribe([wav_path], target_lang="auto")


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> JSONResponse:
    if _asr_model is None:
        return JSONResponse({"error": "model_not_loaded"}, status_code=503)

    original_name = file.filename or "chunk.wav"
    suffix = Path(original_name).suffix.lower() or ".wav"
    tmp_path = Path(tempfile.gettempdir()) / f"stt-{uuid.uuid4().hex}{suffix}"
    try:
        data = await file.read()
        if not data:
            return JSONResponse({"error": "empty_audio"}, status_code=400)
        tmp_path.write_bytes(data)
        result = _run_transcribe(str(tmp_path))
        first = result[0]
        text = first.text if hasattr(first, "text") else str(first)
        return JSONResponse({"text": text or ""})
    except Exception as exc:
        logger.exception("transcribe_failed")
        return JSONResponse(
            {
                "error": type(exc).__name__,
                "detail": str(exc),
                "traceback": traceback.format_exc()[-2000:],
            },
            status_code=500,
        )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("tmp_cleanup_failed", extra={"path": str(tmp_path)})
