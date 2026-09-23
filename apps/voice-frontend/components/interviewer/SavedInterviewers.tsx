"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  roleDraftFromSavedDefinition,
  writeRoleDraft,
  type SavedDefinitionSummary,
} from "@/lib/interviewer/role-draft";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: SavedDefinitionSummary[] };

function formatPublishedAt(value?: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function SavedInterviewers() {
  const router = useRouter();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/admin/definitions?limit=20")
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(
            String(data.error || "Could not load saved interviews."),
          );
        }
        const items = Array.isArray(data.items)
          ? (data.items as SavedDefinitionSummary[])
          : [];
        if (!cancelled) setLoad({ status: "ready", items });
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setLoad({
            status: "error",
            message:
              reason instanceof Error
                ? reason.message
                : "Could not load saved interviews.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function reuse(item: SavedDefinitionSummary) {
    setBusyId(item.definition_id);
    writeRoleDraft(roleDraftFromSavedDefinition(item));
    router.push("/interviewer/admin/invite");
  }

  return (
    <section className="saved-interviewers" aria-label="Saved interviews">
      <div className="saved-interviewers-head">
        <p className="eyebrow">Already published</p>
        <h2>Saved interviews</h2>
        <p>
          Reuse a published definition to invite more candidates — no redesign
          required.
        </p>
      </div>

      {load.status === "loading" ? (
        <p className="saved-interviewers-muted">Loading saved interviews…</p>
      ) : null}

      {load.status === "error" ? (
        <p className="saved-interviewers-muted" role="alert">
          {load.message}
        </p>
      ) : null}

      {load.status === "ready" && load.items.length === 0 ? (
        <p className="saved-interviewers-muted">
          No published interviews yet. Create one to get started.
        </p>
      ) : null}

      {load.status === "ready" && load.items.length > 0 ? (
        <ul className="saved-interviewer-list">
          {load.items.map((item) => (
            <li key={item.definition_id}>
              <div>
                <strong>{item.title}</strong>
                <p>
                  {item.role} · {item.seniority} · {item.duration_minutes} min
                  {formatPublishedAt(item.published_at)
                    ? ` · ${formatPublishedAt(item.published_at)}`
                    : ""}
                </p>
                <span className="saved-definition-id">{item.definition_id}</span>
              </div>
              <button
                type="button"
                className="button primary"
                disabled={busyId === item.definition_id}
                onClick={() => reuse(item)}
              >
                {busyId === item.definition_id ? "Opening…" : "Invite candidates"}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
