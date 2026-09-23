"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const DRAFT_KEY = "ai-interview:role-draft";

type DraftState = { definitionId: string; draft: Record<string, unknown>; title: string; role: string; seniority: string; durationMinutes: string; jobDescription: string; competencies: string; startsAt: string };

function readDraft(): { state?: DraftState; error: string } {
  if (typeof window === "undefined") return { error: "" };
  try {
    const saved = sessionStorage.getItem(DRAFT_KEY);
    return { state: saved ? (JSON.parse(saved) as DraftState) : undefined, error: "" };
  } catch {
    return { error: "The draft could not be loaded." };
  }
}

export default function ReviewAlignmentPage() {
  const [hydrated, setHydrated] = useState(false);
  const [state, setState] = useState<DraftState | undefined>(undefined);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  // sessionStorage is client-only; reading it during render breaks hydration.
  useEffect(() => {
    const boot = readDraft();
    setState(boot.state);
    setError(boot.error);
    setHydrated(true);
  }, []);

  const competencies = state?.draft && Array.isArray(state.draft.competencies) ? state.draft.competencies as Array<Record<string, unknown>> : [];
  const weightTotal = Math.round(competencies.reduce((sum, item) => sum + (Number(item.weight) || 0), 0) * 100) / 100;
  // Publishing rejects weights that do not total 100. Scale proportionally so a
  // recruiter's relative weighting survives; fall back to an even split only
  // when no weights were set at all.
  function rebalance(items: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
    if (items.length === 0) return items;
    const total = items.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
    const scaled = items.map((item) => {
      const share = total > 0 ? (Number(item.weight) || 0) / total : 1 / items.length;
      return Math.round(share * 100 * 100) / 100;
    });
    // Put any rounding remainder on the last entry so the total is exactly 100.
    const head = scaled.slice(0, -1);
    const last = Math.round((100 - head.reduce((sum, value) => sum + value, 0)) * 100) / 100;
    const weights = [...head, last];
    return items.map((item, index) => ({ ...item, weight: weights[index] }));
  }
  function update(index: number, patch: Record<string, unknown>) {
    if (!state) return;
    const next = competencies.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item);
    setState({ ...state, draft: { ...state.draft, competencies: next } });
  }
  function remove(index: number) {
    if (!state) return;
    const dropped = String(competencies[index]?.id || "");
    const next = rebalance(competencies.filter((_, itemIndex) => itemIndex !== index));
    // Scenarios and ladders key off competency_id; leaving orphans behind fails
    // publication with scenario_unknown_competency.
    setState({ ...state, draft: { ...state.draft, competencies: next, ...prunedRefs(dropped) } });
    setSelected(Math.max(0, Math.min(index, next.length - 1)));
  }
  function prunedRefs(droppedId: string): Record<string, unknown> {
    if (!state || !droppedId) return {};
    const pruned: Record<string, unknown> = {};
    for (const key of ["scenario_bank", "question_ladders"]) {
      const list = state.draft[key];
      if (Array.isArray(list)) {
        pruned[key] = list.filter(
          (item) => !item || typeof item !== "object"
            || (item as Record<string, unknown>).competency_id !== droppedId,
        );
      }
    }
    return pruned;
  }
  function move(index: number, direction: -1 | 1) {
    moveTo(index, index + direction);
  }
  function moveTo(fromIndex: number, toIndex: number) {
    if (!state || fromIndex === toIndex || toIndex < 0 || toIndex >= competencies.length) return;
    const next = [...competencies];
    const [moved] = next.splice(fromIndex, 1);
    if (!moved) return;
    next.splice(toIndex, 0, moved);
    setState({ ...state, draft: { ...state.draft, competencies: next } });
    setSelected(toIndex);
  }
  function isComplete(item: Record<string, unknown>): boolean {
    const evidence = Array.isArray(item.evidence_expected) ? item.evidence_expected : [];
    return Boolean(String(item.name || "").trim()) && evidence.length > 0;
  }
  function handleDrop(targetIndex: number) {
    if (draggingIndex !== null) moveTo(draggingIndex, targetIndex);
    setDraggingIndex(null);
    setDragOverIndex(null);
  }
  async function publish() {
    if (!state || competencies.length === 0) return;
    // A draft compiled before rebalancing existed can still carry stale weights
    // and scenarios/ladders pointing at competencies that were removed.
    const balanced = rebalance(competencies);
    const liveIds = new Set(balanced.map((item) => String(item.id || "")));
    const keepLinked = (key: string) => {
      const list = state.draft[key];
      if (!Array.isArray(list)) return undefined;
      return list.filter(
        (item) => !item || typeof item !== "object"
          || liveIds.has(String((item as Record<string, unknown>).competency_id || "")),
      );
    };
    const draft: Record<string, unknown> = { ...state.draft, competencies: balanced };
    for (const key of ["scenario_bank", "question_ladders"]) {
      const kept = keepLinked(key);
      if (kept) draft[key] = kept;
    }
    setBusy(true); setError("");
    try {
      const payload = (definitionId: string) => ({ action: "publish", draft, definitionId, publishedBy: "reference-demo-admin" });
      let definitionId = state.definitionId;
      let response = await fetch("/api/admin/blueprint", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload(definitionId)) });
      let data = await response.json().catch(() => ({}));
      if (response.status === 409) {
        definitionId = `${state.definitionId.replace(/-v\d+$/, "")}-v${Date.now()}`;
        response = await fetch("/api/admin/blueprint", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload(definitionId)) });
        data = await response.json().catch(() => ({}));
      }
      if (!response.ok) throw new Error(String(data.error || data.detail || "Publish failed."));
      const publishedState = { ...state, draft, definitionId, published: data };
      setState(publishedState);
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(publishedState));
      window.location.assign("/interviewer/admin/invite");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Publish failed."); }
    finally { setBusy(false); }
  }

  if (!hydrated) return <main className="interviewer-home admin-builder-page"><div className="center-state"><h2>Loading draft…</h2></div></main>;
  if (!state) return <main className="interviewer-home admin-builder-page"><div className="center-state"><h2>Alignment draft unavailable</h2><Link className="button secondary" href="/interviewer/admin/design">Start role design</Link></div></main>;
  const competency = competencies[selected];
  const fallbackCount = competencies.filter((item) => item.source === "fallback").length;
  return <main className="interviewer-home admin-builder-page">
    <nav className="landing-nav" aria-label="Admin navigation"><Link href="/interviewer/admin/design" className="brand"><span className="brand-mark">AI</span>AI Interviewer</Link><span className="environment-badge">02 Review alignment</span></nav>
    <section className="demo-intro"><p className="eyebrow">Review before publish</p><h1>Shape the interview</h1><p>Choose a competency to edit its details. The published structure will be locked for every candidate.</p></section>
    <section className="demo-card alignment-review admin-review-page">
      {error ? <div className="alert" role="alert">{error}</div> : null}
      {fallbackCount > 0 ? (
        <div className="alert alert-warning" role="status">
          {fallbackCount === 1 ? "1 generic competency was" : `${fallbackCount} generic competencies were`} added because the job description did not yield enough specific skills. Interviews using these will ask general questions. Add more detail to the job description, or rename these to the actual skills you want assessed.
        </div>
      ) : null}
      <div className="competency-picker" aria-label="Interview competencies">
        {competencies.map((item, index) => {
          const complete = isComplete(item);
          return (
            <button
              key={String(item.id || index)}
              type="button"
              className={[
                "competency-picker-item",
                selected === index ? "is-selected" : "",
                dragOverIndex === index && draggingIndex !== null && draggingIndex !== index ? "is-drop-target" : "",
                draggingIndex === index ? "is-dragging" : "",
              ].filter(Boolean).join(" ")}
              onClick={() => setSelected(index)}
              draggable
              onDragStart={() => setDraggingIndex(index)}
              onDragOver={(event) => { event.preventDefault(); setDragOverIndex(index); }}
              onDragLeave={() => setDragOverIndex((current) => (current === index ? null : current))}
              onDrop={() => handleDrop(index)}
              onDragEnd={() => { setDraggingIndex(null); setDragOverIndex(null); }}
            >
              <span className="drag-handle" aria-hidden="true">⠿</span>
              <span className="competency-picker-number">{String(index + 1).padStart(2, "0")}</span>
              <strong>{String(item.name || "Untitled competency")}</strong>
              {item.source === "fallback" ? (
                <span className="competency-status-chip is-draft">Generic</span>
              ) : null}
              <span className={complete ? "competency-status-chip is-complete" : "competency-status-chip is-draft"}>
                {complete ? "✓ Ready" : "Draft"}
              </span>
            </button>
          );
        })}
      </div>
      {competency ? <fieldset
        className={draggingIndex === selected ? "alignment-card is-dragging" : "alignment-card"}
        draggable
        onDragStart={() => setDraggingIndex(selected)}
        onDragOver={(event) => event.preventDefault()}
        onDrop={() => handleDrop(selected)}
        onDragEnd={() => { setDraggingIndex(null); setDragOverIndex(null); }}
      >
        <legend><span className="drag-handle" aria-hidden="true">⠿</span> Competency {selected + 1}</legend>
        <div className="card-order-actions"><button type="button" disabled={selected === 0} onClick={() => move(selected, -1)}>↑</button><button type="button" disabled={selected === competencies.length - 1} onClick={() => move(selected, 1)}>↓</button></div>
        <label>Main topic<input value={String(competency.name || "")} onChange={(e) => update(selected, { name: e.target.value })} /></label>
        <div className="admin-field-grid"><label>Maximum depth<input type="number" min="1" max="5" value={String(competency.max_depth ?? 4)} onChange={(e) => update(selected, { max_depth: Number(e.target.value) })} /></label><label>Maximum follow-ups<input type="number" min="0" max="8" value={String(competency.max_probes ?? 3)} onChange={(e) => update(selected, { max_probes: Number(e.target.value) })} /></label><label>Weighting %<input type="number" min="0" max="100" step="1" value={String(competency.weight ?? 0)} onChange={(e) => update(selected, { weight: Number(e.target.value) })} /></label></div>
        <p className="section-help">Weighting decides how much interview time this competency gets and how much it counts in the score. Totals are normalised to 100% on publish{weightTotal !== 100 ? ` (currently ${weightTotal}%)` : ""}.</p>
        <button className="button danger-button" type="button" onClick={() => remove(selected)}>Delete competency</button>
      </fieldset> : null}
      <div className="admin-page-actions"><span>{competencies.length} competencies · ID {state.definitionId}</span><button className="button primary" disabled={busy || competencies.length === 0} onClick={() => void publish()}>{busy ? "Publishing..." : "Approve and publish"}</button></div>
    </section>
  </main>;
}
