"use client";

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import {
  AdminProgress,
  LandingNav,
} from "@/components/interviewer/LandingNav";
import {
  EMPTY_ROLE_DRAFT,
  defaultStartsAtLocal,
  getRoleDraftSnapshot,
  subscribeRoleDraft,
  writeRoleDraft,
  type RoleDraftState,
} from "@/lib/interviewer/role-draft";

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

function scheduleStartsAt(state: RoleDraftState): string {
  const raw = (state.startsAt || "").trim();
  if (!raw) return new Date().toISOString();
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return new Date().toISOString();
  return parsed.toISOString();
}

export default function InviteCandidatesPage() {
  const ready = useSyncExternalStore(
    subscribeRoleDraft,
    () => true,
    () => false,
  );
  const draftBundle = useSyncExternalStore(
    subscribeRoleDraft,
    getRoleDraftSnapshot,
    () => EMPTY_ROLE_DRAFT,
  );
  const [candidates, setCandidates] = useState<Candidate[]>([
    { name: "", email: "", resume: null },
  ]);
  const [pipeline, setPipeline] = useState<Pipeline>();
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [startsAtOverride, setStartsAtOverride] = useState<string | null>(null);

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

  function setupCompetencies(): string[] {
    const fromPublished = Array.isArray(published?.competencies)
      ? (published.competencies as Array<{ name?: string }>)
          .map((item) => String(item?.name || "").trim())
          .filter(Boolean)
      : [];
    if (fromPublished.length > 0) return fromPublished;
    const fromDraft =
      draft && Array.isArray(draft.competencies)
        ? (draft.competencies as Array<{ name?: string }>)
            .map((item) => String(item?.name || "").trim())
            .filter(Boolean)
        : [];
    if (fromDraft.length > 0) return fromDraft;
    return String(state?.competencies || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  const startsAt =
    startsAtOverride ?? state?.startsAt ?? defaultStartsAtLocal();

  function updateStartsAt(next: string) {
    const value = next || defaultStartsAtLocal();
    setStartsAtOverride(value);
    if (state) writeRoleDraft({ ...state, startsAt: value });
  }

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

  async function copyInvite(index: number, path: string) {
    const absolute =
      typeof window !== "undefined"
        ? `${window.location.origin}${path}`
        : path;
    try {
      await navigator.clipboard.writeText(absolute);
      setCopiedIndex(index);
      window.setTimeout(() => setCopiedIndex(null), 2000);
    } catch {
      update(index, { error: "Could not copy link." });
    }
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
      const schedule = await fetch("/api/interviews", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          candidateId: created.candidate_id,
          definitionId,
          candidateName: candidate.name,
          candidateEmail: candidate.email,
          startsAt: scheduleStartsAt({ ...state, startsAt }),
          joinEarlyMinutes: 15,
          lateGraceMinutes: 120,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          jobDescription: state.jobDescription,
          resumeText: "stored on candidate record",
          interviewSetup: {
            title: state.title,
            role: state.role,
            seniority: state.seniority,
            difficulty: "applied",
            durationMinutes: Number(state.durationMinutes || 30),
            language: "English",
            competencies: setupCompetencies(),
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
        <LandingNav ariaLabel="Admin navigation" badge="03 Invite candidates" />
        <div className="center-state">
          <h2>Choose a published interview</h2>
          <p>
            Publish a new design, or open a saved interview from the home page.
          </p>
          <div className="hero-actions" style={{ justifyContent: "center" }}>
            <Link className="button primary" href="/interviewer">
              Saved interviews
            </Link>
            <Link className="button" href="/interviewer/admin/design">
              Start design
            </Link>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="interviewer-home admin-builder-page">
      <LandingNav ariaLabel="Admin navigation" badge="03 Invite candidates" />
      <AdminProgress current="invite" />
      <section className="demo-intro">
        <p className="eyebrow">Published interview</p>
        <h1>Invite candidates</h1>
        <p>
          Use <strong>{definitionId}</strong> for every candidate. Each gets an
          independent CV, session, transcript, and evaluation.
        </p>
      </section>
      <section className="demo-card invite-page-card">
        <label className="invite-schedule-field">
          Planned start
          <input
            type="datetime-local"
            required
            value={startsAt || defaultStartsAtLocal()}
            onChange={(event) => updateStartsAt(event.target.value)}
          />
          <span className="field-hint">
            Stored in UTC; shown to the candidate in{" "}
            {Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"}.
          </span>
        </label>
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
                <div className="invitation-link-row">
                  <input
                    readOnly
                    value={`${typeof window !== "undefined" ? window.location.origin : ""}${candidate.invite}`}
                  />
                  <button
                    className="button secondary"
                    type="button"
                    onClick={() => void copyInvite(index, candidate.invite!)}
                  >
                    {copiedIndex === index ? "Copied" : "Copy"}
                  </button>
                </div>
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
