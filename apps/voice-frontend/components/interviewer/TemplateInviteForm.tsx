"use client";

import { useEffect, useState } from "react";

import type { RoleDraftState } from "@/lib/interviewer/role-draft";

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

/** Open invite: join anytime for 30 days (no planned-start UI). */
const OPEN_INVITE_GRACE_MINUTES = 43_200;

export function TemplateInviteForm({
  definitionId,
  draft,
  onInvited,
}: {
  definitionId: string;
  draft: RoleDraftState;
  onInvited?: () => void;
}) {
  const [candidates, setCandidates] = useState<Candidate[]>([
    { name: "", email: "", resume: null },
  ]);
  const [pipeline, setPipeline] = useState<Pipeline>();
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  useEffect(() => {
    fetch("/api/admin/pipeline")
      .then((response) => response.json())
      .then(setPipeline)
      .catch(() => undefined);
  }, []);

  function setupCompetencies(): string[] {
    const published = draft.published as Record<string, unknown> | undefined;
    const draftMeta = draft.draft as Record<string, unknown> | undefined;
    const fromPublished = Array.isArray(published?.competencies)
      ? (published.competencies as Array<{ name?: string }>)
          .map((item) => String(item?.name || "").trim())
          .filter(Boolean)
      : [];
    if (fromPublished.length > 0) return fromPublished;
    const fromDraft =
      draftMeta && Array.isArray(draftMeta.competencies)
        ? (draftMeta.competencies as Array<{ name?: string }>)
            .map((item) => String(item?.name || "").trim())
            .filter(Boolean)
        : [];
    if (fromDraft.length > 0) return fromDraft;
    const raw = String(draft.competencies || "").trim();
    if (!raw) return [];
    if (raw.includes("\n")) {
      return raw
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    const parts = raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (
      parts.length > 1 &&
      parts.every(
        (part) =>
          part.length <= 40 &&
          !/^and\b/i.test(part) &&
          !/^(design|develop|test|build|maintain)$/i.test(part),
      )
    ) {
      return parts;
    }
    return [raw];
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
      !definitionId
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
          startsAt: new Date().toISOString(),
          joinEarlyMinutes: 0,
          lateGraceMinutes: OPEN_INVITE_GRACE_MINUTES,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          jobDescription: draft.jobDescription,
          resumeText: "stored on candidate record",
          interviewSetup: {
            title: draft.title,
            role: draft.role,
            seniority: draft.seniority,
            difficulty: "applied",
            durationMinutes: Number(draft.durationMinutes || 30),
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
      onInvited?.();
    } catch (reason) {
      update(index, {
        busy: false,
        error:
          reason instanceof Error ? reason.message : "Invitation failed.",
      });
    }
  }

  return (
    <section className="demo-card invite-page-card template-invite-card">
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
  );
}
