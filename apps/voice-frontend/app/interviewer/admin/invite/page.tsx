"use client";

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

const DRAFT_KEY = "ai-interview:role-draft";

type Candidate = {
  name: string;
  email: string;
  resume: File | null;
  invite?: string;
  error?: string;
  busy?: boolean;
};

type Pipeline = {
  backend: boolean;
  services: Array<{ name: string; provider: string; configured: boolean }>;
};

type DraftBundle = {
  state?: Record<string, unknown>;
  error: string;
};

const EMPTY_DRAFT: DraftBundle = { error: "" };

function readDraft(): DraftBundle {
  try {
    const saved = sessionStorage.getItem(DRAFT_KEY);
    return {
      state: saved ? (JSON.parse(saved) as Record<string, unknown>) : undefined,
      error: "",
    };
  } catch {
    return { error: "Interview definition could not be loaded." };
  }
}

function subscribeDraft() {
  return () => undefined;
}

export default function InviteCandidatesPage() {
  // sessionStorage via useSyncExternalStore — SSR snapshot stays empty; no setState-in-effect.
  const ready = useSyncExternalStore(
    subscribeDraft,
    () => true,
    () => false,
  );
  const draftBundle = useSyncExternalStore(
    subscribeDraft,
    readDraft,
    () => EMPTY_DRAFT,
  );
  const [candidates, setCandidates] = useState<Candidate[]>([
    { name: "", email: "", resume: null },
  ]);
  const [pipeline, setPipeline] = useState<Pipeline>();

  useEffect(() => {
    fetch("/api/admin/pipeline")
      .then((response) => response.json())
      .then(setPipeline)
      .catch(() => undefined);
  }, []);

  const { state, error } = draftBundle;
  const published = state?.published as Record<string, unknown> | undefined;
  const draft = state?.draft as Record<string, unknown> | undefined;
  const definitionId = String(
    published?.definition_id || state?.definitionId || "",
  );

  function update(index: number, patch: Partial<Candidate>) {
    setCandidates((items) =>
      items.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    );
  }

  function addCandidate() {
    setCandidates((items) => [...items, { name: "", email: "", resume: null }]);
  }

  async function invite(index: number) {
    const candidate = candidates[index];
    if (
      !candidate.name.trim() ||
      !candidate.email.trim() ||
      !candidate.resume ||
      !state ||
      !draft
    ) {
      update(index, { error: "Name, email, and CV are required." });
      return;
    }
    update(index, { busy: true, error: undefined });
    try {
      const create = await fetch("/api/admin/candidates", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: candidate.name,
          email: candidate.email,
        }),
      });
      const created = await create.json().catch(() => ({}));
      if (!create.ok) {
        throw new Error(String(created.error || "Candidate creation failed."));
      }
      const form = new FormData();
      form.append("file", candidate.resume);
      const upload = await fetch(
        `/api/admin/candidates/${created.candidate_id}/resume`,
        { method: "POST", body: form },
      );
      if (!upload.ok) throw new Error("CV upload failed.");
      const settings = state as Record<string, unknown>;
      const schedule = await fetch("/api/interviews", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          candidateId: created.candidate_id,
          definitionId,
          candidateName: candidate.name,
          candidateEmail: candidate.email,
          startsAt: new Date().toISOString(),
          joinEarlyMinutes: 0,
          lateGraceMinutes: 120,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          jobDescription: settings.jobDescription,
          resumeText: "stored on candidate record",
          interviewSetup: {
            title: settings.title,
            role: settings.role,
            seniority: settings.seniority,
            difficulty: "applied",
            durationMinutes: Number(settings.durationMinutes || 30),
            language: "English",
            competencies: String(settings.competencies || "")
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
            maxProbesPerPhase: 2,
            monitoringEnabled: true,
            recordingEnabled: false,
          },
        }),
      });
      const scheduled = await schedule.json().catch(() => ({}));
      if (!schedule.ok) {
        throw new Error(
          String(scheduled.error || "Interview scheduling failed."),
        );
      }
      update(index, { invite: String(scheduled.candidatePath), busy: false });
    } catch (reason) {
      update(index, {
        busy: false,
        error:
          reason instanceof Error ? reason.message : "Invitation failed.",
      });
    }
  }

  if (!ready) {
    return (
      <main className="interviewer-home admin-builder-page">
        <div className="center-state">
          <h2>Loading invite workspace…</h2>
        </div>
      </main>
    );
  }

  if (!state || !published) {
    return (
      <main className="interviewer-home admin-builder-page">
        <div className="center-state">
          <h2>Publish the interview first</h2>
          <Link className="button primary" href="/interviewer/admin/design">
            Start design
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="interviewer-home admin-builder-page">
      <nav className="landing-nav" aria-label="Admin navigation">
        <Link href="/interviewer" className="brand">
          <span className="brand-mark">AI</span>AI Interviewer
        </Link>
        <span className="environment-badge">03 Invite candidates</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Published interview</p>
        <h1>Invite candidates</h1>
        <p>
          Use <strong>{definitionId}</strong> for every candidate. Each gets an
          independent CV, session, transcript, and evaluation.
        </p>
      </section>
      <section className="demo-card invite-page-card">
        <div className="pipeline-panel">
          <div>
            <span className="section-number">PIPELINE</span>
            <strong>Provider readiness</strong>
          </div>
          <div className="pipeline-services">
            {pipeline?.services.map((service) => (
              <span
                className={
                  service.configured ? "pipeline-chip is-ready" : "pipeline-chip"
                }
                key={service.name}
              >
                <i />
                {service.name} · {service.provider}
              </span>
            ))}
            <span
              className={
                pipeline?.backend ? "pipeline-chip is-ready" : "pipeline-chip"
              }
            >
              <i />
              Backend
            </span>
          </div>
        </div>
        {error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : null}
        {candidates.map((candidate, index) => (
          <fieldset className="candidate-invite-card" key={index}>
            <legend>Candidate {index + 1}</legend>
            <div className="admin-field-grid">
              <label>
                Name
                <input
                  value={candidate.name}
                  onChange={(e) => update(index, { name: e.target.value })}
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={candidate.email}
                  onChange={(e) => update(index, { email: e.target.value })}
                />
              </label>
              <label>
                CV
                <input
                  type="file"
                  accept=".pdf,.docx,.txt,.md"
                  onChange={(e) =>
                    update(index, { resume: e.target.files?.[0] || null })
                  }
                />
              </label>
            </div>
            {candidate.error ? (
              <p className="candidate-error">{candidate.error}</p>
            ) : null}
            {candidate.invite ? (
              <div className="invitation-link">
                <label>Secure invite link</label>
                <input
                  readOnly
                  value={`${typeof window !== "undefined" ? window.location.origin : ""}${candidate.invite}`}
                />
              </div>
            ) : (
              <button
                className="button primary"
                type="button"
                disabled={candidate.busy}
                onClick={() => void invite(index)}
              >
                {candidate.busy ? "Creating invite..." : "Create candidate invite"}
              </button>
            )}
          </fieldset>
        ))}
        <button
          className="button secondary add-candidate-button"
          type="button"
          onClick={addCandidate}
        >
          + Add another candidate
        </button>
      </section>
    </main>
  );
}
