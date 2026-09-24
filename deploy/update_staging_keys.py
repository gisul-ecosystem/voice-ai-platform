#!/usr/bin/env python3
"""Update staging voice-agent env keys from a local voice-agent .env file.

Reads SARVAM_API_KEY / ELEVENLABS_API_KEY (and related provider settings) from
stdin as KEY=VALUE lines, merges into /etc/voice-ai-platform/voice-agent.env
and backend INTERVIEWER_* provider selection. Never prints secret values.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

VOICE_ENV = Path("/etc/voice-ai-platform/voice-agent.env")
BACKEND_ENV = Path("/etc/voice-ai-platform/backend-api.env")

# Values to sync from local .env (keys only; values come from stdin).
VOICE_KEYS = {
    "STT_PROVIDER",
    "TTS_PROVIDER",
    "SARVAM_API_KEY",
    "SARVAM_STT_BASE_URL",
    "SARVAM_STT_MODEL",
    "SARVAM_STT_MODE",
    "SARVAM_STT_LANGUAGE",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_BASE_URL",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_MODEL_ID",
    "TTS_VOICE",
}


def parse_kv(stream) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in stream:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def upsert(path: Path, updates: dict[str, str]) -> list[str]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    out: list[str] = []
    changed: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in updates:
                nl = "\n" if line.endswith("\n") else ""
                new_line = f"{key}={updates[key]}{nl}"
                if line.rstrip("\n") != new_line.rstrip("\n"):
                    changed.append(key)
                out.append(new_line)
                seen.add(key)
                continue
        out.append(line)
    trailing_nl = text.endswith("\n") or not text
    for key, value in updates.items():
        if key not in seen:
            if out and not out[-1].endswith("\n"):
                out[-1] = out[-1] + "\n"
            out.append(f"{key}={value}\n")
            changed.append(key)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    if path.exists():
        shutil.copy2(path, backup)
    path.write_text("".join(out) + ("" if "".join(out).endswith("\n") or not trailing_nl else "\n"), encoding="utf-8")
    return changed


def main() -> int:
    incoming = parse_kv(sys.stdin)
    voice_updates = {k: incoming[k] for k in VOICE_KEYS if k in incoming and incoming[k]}
    if not voice_updates:
        print("no updates provided on stdin", file=sys.stderr)
        return 2

    # Keep staging STT on Sarvam; TTS follows local choice (openai fallback if set).
    voice_changed = upsert(VOICE_ENV, voice_updates)
    print("voice-agent.env updated:", ",".join(sorted(voice_changed)) or "(unchanged)")

    backend_updates: dict[str, str] = {}
    if "STT_PROVIDER" in voice_updates:
        backend_updates["INTERVIEWER_STT_PROVIDER"] = voice_updates["STT_PROVIDER"]
    if "TTS_PROVIDER" in voice_updates:
        backend_updates["INTERVIEWER_TTS_PROVIDER"] = voice_updates["TTS_PROVIDER"]
    if backend_updates and BACKEND_ENV.exists():
        backend_changed = upsert(BACKEND_ENV, backend_updates)
        print("backend-api.env updated:", ",".join(sorted(backend_changed)) or "(unchanged)")
    else:
        print("backend-api.env skipped")

    # Proof without leaking secrets
    for key in sorted(voice_updates):
        val = voice_updates[key]
        if "KEY" in key:
            print(f"set {key} len={len(val)}")
        else:
            print(f"set {key}={val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
