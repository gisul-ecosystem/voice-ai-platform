"use client";

import Link from "next/link";
import { useDesignForm } from "./useDesignForm";

export default function DesignRolePage() {
  const {
    value,
    busy,
    error,
    newCompetency,
    ingestBusy,
    setField,
    setNewCompetency,
    competencyList,
    setCompetencyList,
    addCompetency,
    ingestDocument,
    ingestTextContent,
    generate,
  } = useDesignForm();

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
        <div className="admin-field-wide">
          <label>Job description <span className="field-required">Required</span></label>
          <div className="document-upload-row">
            <input type="file" accept=".pdf,.docx,.txt,.md,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={ingestBusy} onChange={ingestDocument} />
            <span className="field-help">{ingestBusy ? "Extracting..." : "PDF, DOCX, or text · max 2MB"}</span>
          </div>
          <textarea required rows={12} value={value.jobDescription} onChange={(e) => setField("jobDescription", e.target.value)} placeholder="Paste the job description and responsibilities..." />
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "8px" }}>
            <button type="button" className="button secondary" style={{ padding: "4px 12px", fontSize: "0.8rem", width: "auto" }} disabled={ingestBusy || value.jobDescription.trim().length < 20} onClick={() => ingestTextContent(value.jobDescription)}>{ingestBusy ? "Extracting..." : "Auto-extract Competencies"}</button>
          </div>
        </div>
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
