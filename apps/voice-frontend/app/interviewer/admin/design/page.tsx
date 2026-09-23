"use client";

import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

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

const DEFAULT_VALUE: RoleDraftState = {
  title: "AI Engineer interview",
  role: "AI Engineer",
  seniority: "junior",
  durationMinutes: "30",
  jobDescription: "",
  // Empty = optional guidance only. LLM generates the competency structure from JD/role.
  competencies: "",
  definitionId: "ai-engineer-junior-v1",
  startsAt: defaultStartsAtLocal(),
};

function draftToForm(state?: RoleDraftState): RoleDraftState {
  const startsAt = defaultStartsAtLocal();
  if (!state) return { ...DEFAULT_VALUE, startsAt };
  return {
    definitionId: state.definitionId || DEFAULT_VALUE.definitionId,
    title: state.title || DEFAULT_VALUE.title,
    role: state.role || DEFAULT_VALUE.role,
    seniority: state.seniority || DEFAULT_VALUE.seniority,
    durationMinutes: state.durationMinutes || DEFAULT_VALUE.durationMinutes,
    jobDescription: state.jobDescription || "",
    competencies: state.competencies ?? "",
    startsAt: state.startsAt || startsAt,
    draft: state.draft,
    published: state.published,
  };
}

export default function DesignRolePage() {
  const router = useRouter();
  const ready = useSyncExternalStore(
    subscribeRoleDraft,
    () => true,
    () => false,
  );
  const boot = useSyncExternalStore(
    subscribeRoleDraft,
    getRoleDraftSnapshot,
    () => EMPTY_ROLE_DRAFT,
  );
  const [value, setValue] = useState<RoleDraftState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newCompetency, setNewCompetency] = useState("");

  const form = value ?? (ready ? draftToForm(boot.state) : DEFAULT_VALUE);

  function setField<K extends keyof RoleDraftState>(
    key: K,
    next: RoleDraftState[K],
  ) {
    setValue((current) => {
      const base = current ?? draftToForm(boot.state);
      return { ...base, [key]: next };
    });
  }

  function competencyList(): string[] {
    return form.competencies
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function setCompetencyList(items: string[]) {
    setField("competencies", items.join(", "));
  }

  function addCompetency() {
    const item = newCompetency.trim();
    if (
      !item ||
      competencyList().some(
        (current) => current.toLowerCase() === item.toLowerCase(),
      )
    ) {
      return;
    }
    setCompetencyList([...competencyList(), item]);
    setNewCompetency("");
  }

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const competenciesPayload = form.competencies
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const response = await fetch("/api/admin/blueprint", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "compile",
          title: form.title,
          role: form.role,
          seniority: form.seniority,
          durationMinutes: Number(form.durationMinutes),
          jobDescription: form.jobDescription,
          competencies: competenciesPayload,
          timezone:
            Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          String(data.error || data.detail || "Alignment generation failed."),
        );
      }
      const generatedNames = Array.isArray(data.competencies)
        ? (data.competencies as Array<{ name?: string }>)
            .map((item) => String(item?.name || "").trim())
            .filter(Boolean)
        : [];
      writeRoleDraft({
        ...form,
        competencies:
          generatedNames.length > 0
            ? generatedNames.join(", ")
            : form.competencies,
        draft: data,
        published: undefined,
      });
      router.push("/interviewer/admin/review");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Alignment generation failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="interviewer-home admin-builder-page">
      <LandingNav
        ariaLabel="Admin navigation"
        badge="01 Design role"
      />
      <AdminProgress current="design" />
      <section className="demo-intro">
        <p className="eyebrow">Create an interview</p>
        <h1>Start with the role</h1>
        <p>
          Define the assessment boundary first. The alignment and candidate
          invitations come next.
        </p>
      </section>
      <section className="demo-card admin-section admin-design-page">
        {error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : null}
        <div className="admin-field-grid">
          <label>
            Interview title
            <input
              required
              value={form.title}
              onChange={(e) => setField("title", e.target.value)}
            />
          </label>
          <label>
            Role
            <input
              required
              value={form.role}
              onChange={(e) => setField("role", e.target.value)}
            />
          </label>
          <label>
            Seniority
            <select
              value={form.seniority}
              onChange={(e) => setField("seniority", e.target.value)}
            >
              <option>intern</option>
              <option>junior</option>
              <option>mid</option>
              <option>senior</option>
              <option>lead</option>
            </select>
          </label>
          <label>
            Duration
            <select
              value={form.durationMinutes}
              onChange={(e) => setField("durationMinutes", e.target.value)}
            >
              <option value="15">15 minutes</option>
              <option value="30">30 minutes</option>
              <option value="45">45 minutes</option>
            </select>
          </label>
          <label>
            Planned start
            <input
              type="datetime-local"
              value={form.startsAt}
              onChange={(e) => setField("startsAt", e.target.value)}
            />
          </label>
          <label className="admin-field-wide">
            Job description <span className="field-required">Required</span>
            <textarea
              required
              rows={12}
              value={form.jobDescription}
              onChange={(e) => setField("jobDescription", e.target.value)}
              placeholder="Paste the job description and responsibilities..."
            />
          </label>
          <div className="admin-field-wide competency-input-block">
            <label>
              Assessment areas{" "}
              <span className="field-optional">Optional guidance for the AI</span>
            </label>
            <p className="section-help">
              The AI will infer the interview structure from the job description.
              Add topics here to ensure they are assessed.
            </p>
            <div className="competency-chips">
              {competencyList().map((item) => (
                <span className="competency-chip" key={item}>
                  {item}
                  <button
                    type="button"
                    aria-label={`Remove ${item}`}
                    onClick={() =>
                      setCompetencyList(
                        competencyList().filter((current) => current !== item),
                      )
                    }
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div className="competency-add-row">
              <input
                value={newCompetency}
                placeholder="Add a competency or topic"
                onChange={(e) => setNewCompetency(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addCompetency();
                  }
                }}
              />
              <button
                className="button secondary"
                type="button"
                onClick={addCompetency}
              >
                Add topic
              </button>
            </div>
          </div>
        </div>
        <div className="admin-page-actions">
          <span>AI will create the interview structure from this role</span>
          <button
            className="button primary"
            disabled={busy || !form.jobDescription.trim()}
            onClick={() => void generate()}
          >
            {busy ? "Generating structure..." : "Generate interview structure"}
          </button>
        </div>
      </section>
    </main>
  );
}
