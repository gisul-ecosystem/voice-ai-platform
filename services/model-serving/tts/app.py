"""
Laptop 3 -- TTS node
FastAPI wrapper around Kokoro-82M.
Exposes POST /synthesize accepting text, returns audio bytes (wav).
"""
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import io
import soundfile as sf

app = FastAPI(title="TTS Service - Kokoro-82M")

_pipeline = None


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "af_heart"  # swap for an Indian-English voice pack when available


@app.on_event("startup")
def load_model():
    global _pipeline
    from kokoro import KPipeline
    _pipeline = KPipeline(lang_code="a")


@app.get("/health")
def health():
    return {"status": "ok", "model": "kokoro-82m", "loaded": _pipeline is not None}


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest):
    buf = io.BytesIO()
    for _, _, audio in _pipeline(req.text, voice=req.voice):
        sf.write(buf, audio, 24000, format="WAV")
        break  # first chunk only for now; stream chunks in the LiveKit integration later
    buf.seek(0)
    return Response(content=buf.read(), media_type="audio/wav")
