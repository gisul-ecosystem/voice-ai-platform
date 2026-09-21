import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  const services = [
    { name: "STT", provider: "Sarvam Saaras v3", configured: Boolean(process.env.SARVAM_API_KEY || process.env.STT_API_KEY) },
    { name: "LLM", provider: process.env.LLM_PROVIDER === "openai" ? "OpenAI" : "OpenAI-compatible LLM", configured: Boolean(process.env.OPENAI_API_KEY || process.env.LLM_API_KEY) },
    { name: "TTS", provider: "ElevenLabs", configured: Boolean(process.env.ELEVENLABS_API_KEY || process.env.TTS_API_KEY) },
  ];
  let backend = false;
  if (backendUrl) {
    try { const response = await fetch(`${backendUrl}/health`, { cache: "no-store", signal: AbortSignal.timeout(3000) }); backend = response.ok; } catch { backend = false; }
  }
  return NextResponse.json({ backend, services }, { headers: { "cache-control": "no-store" } });
}
