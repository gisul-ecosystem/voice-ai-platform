"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

function defaultStartTime(): string {
  return new Date(Date.now() + 10 * 60_000).toISOString().slice(0, 16);
}

export default function AdminInterviewPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/interviewer/admin/design");
  }, [router]);
  const [title, setTitle] = useState("AI Engineer interview");
  const [role, setRole] = useState("AI Engineer");
  const [seniority, setSeniority] = useState("junior");
  const [durationMinutes, setDurationMinutes] = useState("30");
  const [jobDescription, setJobDescription] = useState("");
  const [competencies, setCompetencies] = useState("Problem solving, Role expertise, Communication");
  const [definitionId, setDefinitionId] = useState("ai-engineer-junior-v1");
  const [candidateName, setCandidateName] = useState("");
  const [candidateEmail, setCandidateEmail] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [startsAt, setStartsAt] = useState("");
  const [draft, setDraft] = useState<Record<string, unknown>>();
  const [published, setPublished] = useState<Record<string, unknown>>();
  const [invite, setInvite] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draggingCompetency, setDraggingCompetency] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [structureFinalized, setStructureFinalized] = useState(false);
  const [selectedCompetency, setSelectedCompetency] = useState(0);

  useEffect(() => {
    const timer = window.setTimeout(() => setStartsAt(defaultStartTime()), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function jsonRequest(path: string, body: unknown) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(String(data.error || data.detail || "Request failed."));
    return data as Record<string, unknown>;
  }

  async function generateAlignment() {
    setBusy(true); setError("");
    try {
      const data = await jsonRequest("/api/admin/blueprint", {
        action: "compile", title, seniority, durationMinutes: Number(durationMinutes),
        jobDescription, competencies: competencies.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setDraft(data);
      setStructureFinalized(false);
      setSelectedCompetency(0);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Alignment generation failed."); }
    finally { setBusy(false); }
  }

  async function publishAndInvite() {
    if (!draft || !resume) { setError("Review the alignment and choose a CV before publishing."); return; }
    setBusy(true); setError("");
    try {
      const definition = await jsonRequest("/api/admin/blueprint", {
        action: "publish", draft, definitionId, publishedBy: "reference-demo-admin",
      });
      setPublished(definition);
      const candidate = await jsonRequest("/api/admin/candidates", {
        name: candidateName, email: candidateEmail,
      });
      const form = new FormData(); form.append("file", resume);
      const uploaded = await fetch(`/api/admin/candidates/${candidate.candidate_id}/resume`, { method: "POST", body: form });
      if (!uploaded.ok) throw new Error("Candidate CV upload failed.");
      const scheduled = await jsonRequest("/api/interviews", {
        candidateId: candidate.candidate_id, definitionId: definition.definition_id,
        candidateName, candidateEmail, startsAt: new Date(startsAt).toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        jobDescription, resumeText: "stored on candidate record",
        interviewSetup: {
          title, role, seniority, difficulty: "applied", durationMinutes: Number(durationMinutes),
          language: "English", competencies: competencies.split(",").map((item) => item.trim()).filter(Boolean),
          maxProbesPerPhase: 2, monitoringEnabled: true, recordingEnabled: false,
        },
      });
      setInvite(String(scheduled.candidatePath));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Publishing failed."); }
    finally { setBusy(false); }
  }

  function updateCompetency(index: number, patch: Record<string, unknown>) {
    if (!draft || !Array.isArray(draft.competencies)) return;
    const next = draft.competencies.map((item, itemIndex) =>
      itemIndex === index && item && typeof item === "object"
        ? { ...(item as Record<string, unknown>), ...patch }
        : item,
    );
    setDraft({ ...draft, competencies: next });
  }

  function moveCompetency(fromIndex: number, toIndex: number) {
    if (!draft || fromIndex === toIndex || !Array.isArray(draft.competencies)) return;
    const competencies = [...draft.competencies];
    const [moved] = competencies.splice(fromIndex, 1);
    if (moved === undefined) return;
    competencies.splice(toIndex, 0, moved);

    const ladders = Array.isArray(draft.question_ladders)
      ? [...draft.question_ladders]
      : [];
    const movedId = moved && typeof moved === "object"
      ? String((moved as Record<string, unknown>).id || "")
      : "";
    const ladder = ladders.find(
      (item) => item && typeof item === "object" &&
        String((item as Record<string, unknown>).competency_id || "") === movedId,
    );
    const withoutLadder = ladders.filter((item) => item !== ladder);
    const targetId = competencies[toIndex] && typeof competencies[toIndex] === "object"
      ? String((competencies[toIndex] as Record<string, unknown>).id || "")
      : "";
    const targetLadderIndex = withoutLadder.findIndex(
      (item) => item && typeof item === "object" &&
        String((item as Record<string, unknown>).competency_id || "") === targetId,
    );
    if (ladder) withoutLadder.splice(targetLadderIndex < 0 ? withoutLadder.length : targetLadderIndex, 0, ladder);
    setDraft({ ...draft, competencies, question_ladders: withoutLadder });
    setSelectedCompetency(toIndex);
    setDraggingCompetency(null);
  }

  function deleteCompetency(index: number) {
    if (!draft || !Array.isArray(draft.competencies)) return;
    const removed = draft.competencies[index];
    const removedId = removed && typeof removed === "object"
      ? String((removed as Record<string, unknown>).id || "")
      : "";
    const competencies = draft.competencies.filter((_, itemIndex) => itemIndex !== index);
    const question_ladders = Array.isArray(draft.question_ladders)
      ? draft.question_ladders.filter((item) =>
        !item || typeof item !== "object" ||
        String((item as Record<string, unknown>).competency_id || "") !== removedId,
      )
      : [];
    setDraft({ ...draft, competencies, question_ladders });
    setSelectedCompetency(Math.max(0, Math.min(index, competencies.length - 1)));
    setStructureFinalized(false);
  }

  const alignmentCompetencies = draft && Array.isArray(draft.competencies)
    ? (draft.competencies as Array<Record<string, unknown>>)
    : [];
  const alignmentStep = structureFinalized ? (published ? 3 : 2) : 1;
  const candidateUrl = invite && typeof window !== "undefined"
    ? `${window.location.origin}${invite}`
    : invite;

  return (
    <main className="interviewer-home admin-builder-page">
      <nav className="landing-nav" aria-label="AI Interviewer administration navigation">
        <Link href="/interviewer" className="brand">
          <span className="brand-mark" aria-hidden="true">AI</span>
          AI Interviewer
        </Link>
        <span className="environment-badge">Admin workspace</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Create an interview</p>
        <h1>Build the interview alignment</h1>
        <p>Create the role alignment once, lock its definition, then reuse it for a candidate.</p>
      </section>
      <div className="admin-progress" aria-label="Interview creation progress">
        {[[1, "Design role"], [2, "Review alignment"], [3, "Invite candidate"]].map(([step, label]) => (
          <div className={alignmentStep >= Number(step) ? "admin-progress-step is-active" : "admin-progress-step"} key={String(step)}>
            <span>{step}</span><strong>{label}</strong>
          </div>
        ))}
      </div>
      <section className="demo-card recruiter-setup-shell">
        {error ? <div className="alert" role="alert">{error}</div> : null}
        <fieldset className="admin-section admin-section-design">
          <legend><span className="section-number">01</span> Design role</legend>
          <p className="section-help">Set the assessment boundary. The AI will propose the interview alignment from these inputs.</p>
          <div className="admin-field-grid">
            <label>Interview title<input required value={title} onChange={(event) => setTitle(event.target.value)} /></label>
            <label>Role<input required value={role} onChange={(event) => setRole(event.target.value)} /></label>
            <label>Seniority<select value={seniority} onChange={(event) => setSeniority(event.target.value)}><option>intern</option><option>junior</option><option>mid</option><option>senior</option><option>lead</option></select></label>
            <label>Duration<select value={durationMinutes} onChange={(event) => setDurationMinutes(event.target.value)}><option value="15">15 minutes</option><option value="30">30 minutes</option><option value="45">45 minutes</option></select></label>
            <label className="admin-field-wide">Job description <span className="field-required">Required</span><textarea required value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} rows={7} placeholder="Paste the job description and responsibilities..." /></label>
            <label className="admin-field-wide">Assessment areas <span className="field-optional">Comma separated</span><input value={competencies} onChange={(event) => setCompetencies(event.target.value)} /></label>
          </div>
          <button className="button secondary" type="button" disabled={busy || !jobDescription.trim()} onClick={generateAlignment}>{busy ? "Generating..." : "Generate alignment"}</button>
        </fieldset>
        {draft ? <div className="alignment-review" role="status">
          <div className="alignment-review-heading"><div><span className="section-number">02</span><strong>Review alignment</strong></div><span className="review-badge">Editable draft</span></div>
          <p>Finalize the competency order first. Select a competency to edit its details or remove it from the interview.</p>
          <div className="competency-picker" aria-label="Interview competencies">
            {alignmentCompetencies.map((competency, index) => (
              <button
                className={selectedCompetency === index ? "competency-picker-item is-selected" : "competency-picker-item"}
                key={String(competency.id || index)}
                type="button"
                onClick={() => setSelectedCompetency(index)}
                draggable
                onDragStart={() => setDraggingCompetency(index)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => { if (draggingCompetency !== null) moveCompetency(draggingCompetency, index); }}
              >
                <span className="competency-picker-number">{String(index + 1).padStart(2, "0")}</span>
                <strong>{String(competency.name || "Untitled competency")}</strong>
                <span aria-hidden="true">›</span>
              </button>
            ))}
          </div>
          {alignmentCompetencies[selectedCompetency] && (() => {
            const competency = alignmentCompetencies[selectedCompetency];
            const index = selectedCompetency;
            const evidence = Array.isArray(competency.evidence_expected)
              ? competency.evidence_expected.map(String).join(", ")
              : "";
            return <fieldset
              key={String(competency.id || index)}
              className={draggingCompetency === index ? "alignment-card is-dragging" : "alignment-card"}
              draggable
              onDragStart={() => setDraggingCompetency(index)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={() => {
                if (draggingCompetency !== null) moveCompetency(draggingCompetency, index);
              }}
              onDragEnd={() => setDraggingCompetency(null)}
            >
              <legend><span className="drag-handle" aria-hidden="true">::</span> {String(competency.name || `Competency ${index + 1}`)}</legend>
              <div className="card-order-actions">
                <button type="button" aria-label={`Move competency ${index + 1} up`} disabled={index === 0} onClick={() => moveCompetency(index, index - 1)}>↑</button>
                <button type="button" aria-label={`Move competency ${index + 1} down`} disabled={index === alignmentCompetencies.length - 1} onClick={() => moveCompetency(index, index + 1)}>↓</button>
              </div>
              <label>Name<input value={String(competency.name || "")} onChange={(event) => updateCompetency(index, { name: event.target.value })} /></label>
              <label>Definition<textarea rows={3} value={String(competency.definition || "")} onChange={(event) => updateCompetency(index, { definition: event.target.value })} /></label>
              <label>Expected evidence<input value={evidence} onChange={(event) => updateCompetency(index, { evidence_expected: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label>
              <label>Weightage (%)<input type="number" min="0" max="100" value={String(competency.weight ?? "")} onChange={(event) => updateCompetency(index, { weight: event.target.value ? Number(event.target.value) : null })} /></label>
              <label>Maximum depth<input type="number" min="1" max="5" value={String(competency.max_depth ?? 4)} onChange={(event) => updateCompetency(index, { max_depth: Number(event.target.value) })} /></label>
              <label>Maximum follow-ups<input type="number" min="0" max="8" value={String(competency.max_probes ?? 3)} onChange={(event) => updateCompetency(index, { max_probes: Number(event.target.value) })} /></label>
              <button className="button danger-button" type="button" onClick={() => deleteCompetency(index)}>Delete competency</button>
            </fieldset>;
          })()}
          <div className="alignment-finalize-bar">
            <span>{alignmentCompetencies.length} competencies in interview structure</span>
            <button className="button primary" type="button" disabled={alignmentCompetencies.length === 0} onClick={() => setStructureFinalized(true)}>
              Finalize interview structure
            </button>
          </div>
        </div> : null}
        {draft && structureFinalized ? <fieldset className="admin-section admin-section-candidate">
          <legend><span className="section-number">03</span> Invite candidate</legend>
          <p className="section-help">Upload the CV here. The candidate only receives the secure interview link.</p>
          <div className="admin-field-grid">
            <label>Candidate name<input required value={candidateName} onChange={(event) => setCandidateName(event.target.value)} /></label>
            <label>Candidate email<input required type="email" value={candidateEmail} onChange={(event) => setCandidateEmail(event.target.value)} /></label>
            <label>Candidate CV <span className="field-required">Required</span><input required type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => setResume(event.target.files?.[0] || null)} /></label>
            <label>Interview start<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /></label>
          </div>
          <label>Published definition ID <span className="field-optional">Use a new version ID for future edits</span><input value={definitionId} onChange={(event) => setDefinitionId(event.target.value)} /></label>
          <button className="button primary" type="button" disabled={busy || !draft || !candidateName.trim() || !candidateEmail.trim() || !resume} onClick={publishAndInvite}>{busy ? "Publishing..." : "Approve, publish and create invite"}</button>
          {published ? <p className="published-status" role="status"><span>Locked</span> Definition: <strong>{String(published.definition_id)}</strong></p> : null}
          {candidateUrl ? <div className="invitation-link"><label htmlFor="invite-link">Candidate invite link</label><div className="copy-field"><input id="invite-link" readOnly value={candidateUrl} /><button className="button secondary" type="button" onClick={async () => { try { await navigator.clipboard.writeText(candidateUrl); setCopied(true); } catch { setError("Copy was blocked. Select the link manually."); } }}>{copied ? "Copied" : "Copy link"}</button></div><p className="form-note" role="status">{copied ? "Invite link copied." : "Share this secure link with the candidate."}</p></div> : null}
        </fieldset> : null}
      </section>
    </main>
  );
}
