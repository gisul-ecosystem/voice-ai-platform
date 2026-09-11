# TTS node (Laptop 3)

Kokoro-82M, <1GB VRAM. This laptop has the most spare capacity, so it also
runs Redis for shared session state across all services.

**Accent note (important, verified against the official repo):** Kokoro does
NOT have a native Indian-accented English voice. Its voice packs are American
English (`af_*`/`am_*`), British English (`bf_*`/`bm_*`), and separately
Hindi (`hf_*`/`hm_*` -- a different language, not an Indian accent on English
speech). Current placeholder uses American English (`af_heart`). For an
actual Indian-accented English voice, evaluate CosyVoice 2 (voice cloning
from a reference sample) as the real solution -- don't assume Kokoro covers
this out of the box.

Run: `python -m uvicorn app:app --host 0.0.0.0 --port 5553`
Redis: `docker run -d -p 6379:6379 redis`
Test: `curl -X POST http://localhost:5553/synthesize -H "Content-Type: application/json" -d '{"text":"Hello candidate"}' --output out.wav`
