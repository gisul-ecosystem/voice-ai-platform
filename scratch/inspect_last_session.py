import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)
    db = client["voiceai_pilot"]

    sessions = await db["interview_sessions"].find().sort("created_at", -1).to_list(5)
    print("Recent Sessions:")
    for s in sessions:
        sid = s.get("_id") or s.get("session_id")
        created = s.get("created_at")
        status = s.get("status")
        print(f"  {sid} | created={created} | status={status}")

    if not sessions:
        print("No sessions found.")
        return

    latest = sessions[0]
    sid = latest.get("_id") or latest.get("session_id")
    print("\n" + "="*80)
    print(f"LATEST SESSION: {sid}")
    print("="*80)

    # Context / Resume info
    ctx_id = latest.get("context_id")
    defn_id = latest.get("definition_id")
    if defn_id:
        defn = await db["interview_definitions"].find_one({"_id": defn_id})
        if defn:
            comps = defn.get("competencies", [])
            print("Configured Competencies in Definition:")
            for c in comps:
                print(f"  - {c.get('id')}: {c.get('name')} (weight={c.get('weight')}, req_intents={c.get('required_intents')})")

    # Turns
    turns = await db["interview_turns"].find({"session_id": sid}).sort("created_at", 1).to_list(200)
    print(f"\n--- TURNS ({len(turns)} turns) ---")
    for i, t in enumerate(turns):
        role = (t.get("role") or "?").upper()
        text = t.get("text") or t.get("content") or ""
        ts = str(t.get("created_at", ""))
        print(f"Turn {i+1} [{role}]: {text}\n")

    # Questions with policy actions
    questions = await db["interview_questions"].find({"session_id": sid}).sort("asked_at", 1).to_list(100)
    print(f"\n--- QUESTIONS ASKED ({len(questions)}) ---")
    for i, q in enumerate(questions):
        action = q.get("policy_action", "?")
        comp = q.get("competency_id", "?")
        intent = q.get("intent", "?")
        depth = q.get("depth", "?")
        ok = q.get("validator_ok", "?")
        reasons = q.get("validator_reasons") or []
        text = q.get("text", "")
        print(f"Q{i+1}: comp={comp} | intent={intent} | depth={depth} | action={action} | ok={ok}")
        print(f"    Text: {text}")
        if reasons:
            print(f"    Validator reasons: {reasons}")
        print()

    # Brain snapshot
    brain = await db["interview_brain_snapshots"].find_one({"session_id": sid})
    if brain:
        print("\n--- FINAL BRAIN SNAPSHOT ---")
        print(f"Section: {brain.get('current_section')} | Phase Index: {brain.get('phase_index')}")
        print(f"Elapsed: {brain.get('elapsed_seconds')}s | Max: {brain.get('max_seconds')}s")
        cov = brain.get("coverage") or {}
        print("Competency Coverage:")
        for cid, row in cov.items():
            print(f"  {cid}: {row}")

    client.close()

if __name__ == "__main__":
    asyncio.run(main())
