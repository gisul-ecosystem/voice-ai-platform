"use client";

import Link from "next/link";
import { useState } from "react";

const defaultStart = new Date(Date.now() + 10 * 60_000).toISOString().slice(0, 16);
const DRAFT_KEY = "ai-interview:role-draft";

type RoleDraft = {
  title: string; role: string; seniority: string; durationMinutes: string;
  jobDescription: string; competencies: string; definitionId: string; startsAt: string;
  difficulty: string; language: string;
  monitoringEnabled: boolean; recordingEnabled: boolean;
  draft?: Record<string, unknown>;
};

export default function DesignRolePage() {
  const [value, setValue] = useState<RoleDraft>({
    title: "AI Engineer interview", role: "AI Engineer", seniority: "junior",
    durationMinutes: "30", jobDescription: "", competencies: "",
    definitionId: "ai-engineer-junior-v1", startsAt: defaultStart,
    difficulty: "applied", language: "English",
    monitoringEnabled: true, recordingEnabled: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newCompetency, setNewCompetency] = useState("");

  function setField<K extends keyof RoleDraft>(key: K, next: RoleDraft[K]) {
    setValue((current) => ({ ...current, [key]: next }));
  }

  function competencyList(): string[] {
    return value.competencies.split(",").map((item) => item.trim()).filter(Boolean);
  }

  function setCompetencyList(items: string[]) {
    setField("competencies", items.join(", "));
  }

  function addCompetency() {
    const item = newCompetency.trim();
    if (!item || competencyList().some((current) => current.toLowerCase() === item.toLowerCase())) return;
    setCompetencyList([...competencyList(), item]);
    setNewCompetency("");
  }

  async function generate() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/admin/blueprint", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
        action: "compile", title: value.title, seniority: value.seniority, durationMinutes: Number(value.durationMinutes),
        language: value.language, jobDescription: value.jobDescription,
        competencies: value.competencies.split(",").map((item) => item.trim()).filter(Boolean),
      }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(data.error || data.detail || "Alignment generation failed."));
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ ...value, draft: data }));
      window.location.assign("/interviewer/admin/review");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Alignment generation failed."); }
    finally { setBusy(false); }
  }

  return <main className="interviewer-home admin-builder-page">
    <nav className="landing-nav" aria-label="Admin navigation"><Link href="/interviewer" className="brand"><span className="brand-mark">AI</span>AI Interviewer</Link><span className="environment-badge">01 Design role</span></nav>
    <section className="demo-intro"><p className="eyebrow">Create an interview</p><h1>Start with the role</h1><p>Define the assessment boundary first. The alignment and candidate invitations come next.</p></section>
    <section className="demo-card admin-section admin-design-page">
      {error ? <div className="alert" role="alert">{error}</div> : null}
      <div className="admin-field-grid">
        <label>Interview title<input required value={value.title} onChange={(e) => setField("title", e.target.value)} /></label>
        <label>Role<input required value={value.role} onChange={(e) => setField("role", e.target.value)} /></label>
        <label>Seniority<select value={value.seniority} onChange={(e) => setField("seniority", e.target.value)}><option>intern</option><option>junior</option><option>mid</option><option>senior</option><option>lead</option></select></label>
        <label>Duration<select value={value.durationMinutes} onChange={(e) => setField("durationMinutes", e.target.value)}><option value="15">15 minutes</option><option value="30">30 minutes</option><option value="45">45 minutes</option></select></label>
        <label>Question depth
          <select value={value.difficulty} onChange={(e) => setField("difficulty", e.target.value)}>
            <option value="foundational">Foundational — concepts and approach</option>
            <option value="applied">Applied — adds cost and trade-offs</option>
            <option value="diagnostic">Diagnostic — adds failure modes</option>
            <option value="strategic">Strategic — full depth incl. optimisation</option>
          </select>
        </label>
        <label>Interview language<input required maxLength={32} value={value.language} onChange={(e) => setField("language", e.target.value)} /></label>
        <div className="admin-field-wide">
          <label className="policy-option">
            <input type="checkbox" checked={value.monitoringEnabled} onChange={(e) => setField("monitoringEnabled", e.target.checked)} />
            <span><strong>Human monitoring</strong><small>Allow an authorised reviewer to listen silently after disclosure.</small></span>
          </label>
          <label className="policy-option">
            <input type="checkbox" checked={value.recordingEnabled} onChange={(e) => setField("recordingEnabled", e.target.checked)} />
            <span><strong>Session recording</strong><small>Record the interview only after explicit candidate consent.</small></span>
          </label>
        </div>
        <label className="admin-field-wide">Job description <span className="field-required">Required</span><textarea required rows={12} value={value.jobDescription} onChange={(e) => setField("jobDescription", e.target.value)} placeholder="Paste the job description and responsibilities..." /></label>
        <div className="admin-field-wide competency-input-block">
          <label>Assessment areas <span className="field-optional">Optional — leave empty to use the job description</span></label>
          <p className="section-help">Competencies are extracted from the job description automatically, and you can edit them on the next screen. Only add topics here to force something the job description does not mention — anything added takes priority and reduces the number of competencies drawn from the job description.</p>
          <div className="competency-chips">
            {competencyList().map((item) => (
              <span className="competency-chip" key={item}>
                {item}
                <button type="button" aria-label={`Remove ${item}`} onClick={() => setCompetencyList(competencyList().filter((current) => current !== item))}>×</button>
              </span>
            ))}
          </div>
          <div className="competency-add-row">
            <input value={newCompetency} placeholder="Add a competency or topic" onChange={(e) => setNewCompetency(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCompetency(); } }} />
            <button className="button secondary" type="button" onClick={addCompetency}>Add topic</button>
          </div>
        </div>
      </div>
      <div className="admin-page-actions"><span>AI will create the interview structure from this role</span><button className="button primary" disabled={busy || !value.jobDescription.trim()} onClick={() => void generate()}>{busy ? "Generating structure..." : "Generate interview structure"}</button></div>
    </section>
  </main>;
}
