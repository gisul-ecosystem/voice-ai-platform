"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import {
  AdminProgress,
  LandingNav,
} from "@/components/interviewer/LandingNav";
import {
  EMPTY_ROLE_DRAFT,
  getRoleDraftSnapshot,
  subscribeRoleDraft,
  writeRoleDraft,
  type RoleDraftState,
} from "@/lib/interviewer/role-draft";

export default function ReviewAlignmentPage() {
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
  const [edits, setEdits] = useState<RoleDraftState | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  const state = edits ?? boot.state;
  const displayError = error || (edits === null ? boot.error : "");

  const competencies =
    state?.draft && Array.isArray(state.draft.competencies)
      ? (state.draft.competencies as Array<Record<string, unknown>>)
      : [];

  function setState(next: RoleDraftState) {
    setEdits(next);
    writeRoleDraft(next);
  }

  function update(index: number, patch: Record<string, unknown>) {
    if (!state) return;
    const next = competencies.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item,
    );
    setState({ ...state, draft: { ...state.draft, competencies: next } });
  }

  function remove(index: number) {
    if (!state) return;
    const next = competencies.filter((_, itemIndex) => itemIndex !== index);
    setState({ ...state, draft: { ...state.draft, competencies: next } });
    setSelected(Math.max(0, Math.min(index, next.length - 1)));
  }

  function move(index: number, direction: -1 | 1) {
    moveTo(index, index + direction);
  }

  function moveTo(fromIndex: number, toIndex: number) {
    if (
      !state ||
      fromIndex === toIndex ||
      toIndex < 0 ||
      toIndex >= competencies.length
    ) {
      return;
    }
    const next = [...competencies];
    const [moved] = next.splice(fromIndex, 1);
    if (!moved) return;
    next.splice(toIndex, 0, moved);
    setState({ ...state, draft: { ...state.draft, competencies: next } });
    setSelected(toIndex);
  }

  function isComplete(item: Record<string, unknown>): boolean {
    const evidence = Array.isArray(item.evidence_expected)
      ? item.evidence_expected
      : [];
    return Boolean(String(item.name || "").trim()) && evidence.length > 0;
  }

  function evidenceText(item: Record<string, unknown>): string {
    const evidence = Array.isArray(item.evidence_expected)
      ? item.evidence_expected
      : [];
    return evidence.map(String).join(", ");
  }

  function handleDrop(targetIndex: number) {
    if (draggingIndex !== null) moveTo(draggingIndex, targetIndex);
    setDraggingIndex(null);
    setDragOverIndex(null);
  }

  async function publish() {
    if (!state || competencies.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const payload = (definitionId: string) => ({
        action: "publish",
        draft: state.draft,
        definitionId,
        publishedBy: "reference-demo-admin",
      });
      let definitionId = state.definitionId;
      let response = await fetch("/api/admin/blueprint", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload(definitionId)),
      });
      let data = await response.json().catch(() => ({}));
      if (response.status === 409) {
        definitionId = `${state.definitionId.replace(/-v\d+$/, "")}-v${Date.now()}`;
        response = await fetch("/api/admin/blueprint", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload(definitionId)),
        });
        data = await response.json().catch(() => ({}));
      }
      if (!response.ok) {
        throw new Error(String(data.error || data.detail || "Publish failed."));
      }
      const publishedState = { ...state, definitionId, published: data };
      setState(publishedState);
      router.push("/interviewer/admin/invite");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Publish failed.");
    } finally {
      setBusy(false);
    }
  }

  if (!ready) {
    return (
      <main className="interviewer-home admin-builder-page">
        <div className="center-state">
          <h2>Loading alignment…</h2>
        </div>
      </main>
    );
  }

  if (!state?.draft) {
    return (
      <main className="interviewer-home admin-builder-page">
        <LandingNav ariaLabel="Admin navigation" badge="02 Review alignment" />
        <div className="center-state">
          <h2>Alignment draft unavailable</h2>
          <Link className="button secondary" href="/interviewer/admin/design">
            Start role design
          </Link>
          {displayError ? <p className="error-text">{displayError}</p> : null}
        </div>
      </main>
    );
  }

  const competency = competencies[selected];
  return (
    <main className="interviewer-home admin-builder-page">
      <LandingNav ariaLabel="Admin navigation" badge="02 Review alignment" />
      <AdminProgress current="review" />
      <section className="demo-intro">
        <p className="eyebrow">Review before publish</p>
        <h1>Shape the interview</h1>
        <p>
          Choose a competency to edit its details. The published structure will
          be locked for every candidate.
        </p>
      </section>
      <section className="demo-card alignment-review admin-review-page">
        {displayError ? (
          <div className="alert" role="alert">
            {displayError}
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
                  dragOverIndex === index &&
                  draggingIndex !== null &&
                  draggingIndex !== index
                    ? "is-drop-target"
                    : "",
                  draggingIndex === index ? "is-dragging" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => setSelected(index)}
                draggable
                onDragStart={() => setDraggingIndex(index)}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragOverIndex(index);
                }}
                onDragLeave={() =>
                  setDragOverIndex((current) =>
                    current === index ? null : current,
                  )
                }
                onDrop={() => handleDrop(index)}
                onDragEnd={() => {
                  setDraggingIndex(null);
                  setDragOverIndex(null);
                }}
              >
                <span className="drag-handle" aria-hidden="true">
                  ⠿
                </span>
                <span className="competency-picker-number">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <strong>{String(item.name || "Untitled competency")}</strong>
                <span
                  className={
                    complete
                      ? "competency-status-chip is-complete"
                      : "competency-status-chip is-draft"
                  }
                >
                  {complete ? "✓ Ready" : "Draft"}
                </span>
              </button>
            );
          })}
        </div>
        {competency ? (
          <fieldset
            className={
              draggingIndex === selected
                ? "alignment-card is-dragging"
                : "alignment-card"
            }
            draggable
            onDragStart={() => setDraggingIndex(selected)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => handleDrop(selected)}
            onDragEnd={() => {
              setDraggingIndex(null);
              setDragOverIndex(null);
            }}
          >
            <legend>
              <span className="drag-handle" aria-hidden="true">
                ⠿
              </span>{" "}
              Competency {selected + 1}
            </legend>
            <div className="card-order-actions">
              <button
                type="button"
                disabled={selected === 0}
                onClick={() => move(selected, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                disabled={selected === competencies.length - 1}
                onClick={() => move(selected, 1)}
              >
                ↓
              </button>
            </div>
            <label>
              Main topic
              <input
                value={String(competency.name || "")}
                onChange={(e) => update(selected, { name: e.target.value })}
              />
            </label>
            <label>
              Evidence expected
              <input
                value={evidenceText(competency)}
                placeholder="Comma-separated signals (ownership, metrics, …)"
                onChange={(e) =>
                  update(selected, {
                    evidence_expected: e.target.value
                      .split(",")
                      .map((part) => part.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
            <div className="admin-field-grid">
              <label>
                Maximum depth
                <input
                  type="number"
                  min="1"
                  max="5"
                  value={String(competency.max_depth ?? 4)}
                  onChange={(e) =>
                    update(selected, { max_depth: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Maximum follow-ups
                <input
                  type="number"
                  min="0"
                  max="8"
                  value={String(competency.max_probes ?? 3)}
                  onChange={(e) =>
                    update(selected, { max_probes: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                Weight
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={String(competency.weight ?? 1)}
                  onChange={(e) =>
                    update(selected, { weight: Number(e.target.value) })
                  }
                />
              </label>
            </div>
            <button
              className="button danger-button"
              type="button"
              onClick={() => remove(selected)}
            >
              Delete competency
            </button>
          </fieldset>
        ) : null}
        <div className="admin-page-actions">
          <span>
            {competencies.length} competencies · ID {state.definitionId}
          </span>
          <button
            className="button primary"
            disabled={busy || competencies.length === 0}
            onClick={() => void publish()}
          >
            {busy ? "Publishing..." : "Approve and publish"}
          </button>
        </div>
      </section>
    </main>
  );
}
