"use client";

import { useEffect, useState } from "react";

type InviteRow = {
  interviewId: string;
  definitionId?: string | null;
  candidateName: string;
  candidateEmail: string;
  status: string;
  startsAt?: string | null;
  invitationToken?: string | null;
  candidatePath?: string | null;
  createdAt?: string | null;
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: InviteRow[] };

function formatWhen(value?: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function TemplateInvitesList({
  definitionId,
  refreshKey = 0,
}: {
  definitionId: string;
  refreshKey?: number;
}) {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(
      `/api/admin/interviews?definitionId=${encodeURIComponent(definitionId)}&limit=50`,
    )
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(String(data.error || "Could not load invites."));
        }
        if (!cancelled) {
          setLoad({
            status: "ready",
            items: Array.isArray(data.items) ? (data.items as InviteRow[]) : [],
          });
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setLoad({
            status: "error",
            message:
              reason instanceof Error
                ? reason.message
                : "Could not load invites.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [definitionId, refreshKey]);

  async function copyPath(interviewId: string, path: string) {
    const absolute =
      typeof window !== "undefined"
        ? `${window.location.origin}${path}`
        : path;
    try {
      await navigator.clipboard.writeText(absolute);
      setCopiedId(interviewId);
      window.setTimeout(() => setCopiedId(null), 2000);
    } catch {
      setLoad({ status: "error", message: "Could not copy link." });
    }
  }

  function refresh() {
    setLoad({ status: "loading" });
    fetch(
      `/api/admin/interviews?definitionId=${encodeURIComponent(definitionId)}&limit=50`,
    )
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(String(data.error || "Could not load invites."));
        }
        setLoad({
          status: "ready",
          items: Array.isArray(data.items) ? (data.items as InviteRow[]) : [],
        });
      })
      .catch((reason: unknown) => {
        setLoad({
          status: "error",
          message:
            reason instanceof Error
              ? reason.message
              : "Could not load invites.",
        });
      });
  }

  return (
    <section className="demo-card admin-section">
      <div className="saved-interviewers-head" style={{ marginBottom: 16 }}>
        <p className="eyebrow">For this template</p>
        <h2>Invites</h2>
        <p>
          Copy a candidate link again, or create a new invite from the Invite
          tab.
        </p>
      </div>
      {load.status === "error" ? (
        <div className="alert" role="alert">
          {load.message}
        </div>
      ) : null}
      {load.status === "loading" ? (
        <p className="saved-interviewers-muted">Loading invites…</p>
      ) : null}
      {load.status === "ready" && load.items.length === 0 ? (
        <p className="saved-interviewers-muted">
          No invites yet. Use the Invite tab to create the first link.
        </p>
      ) : null}
      {load.status === "ready" && load.items.length > 0 ? (
        <ul className="saved-interviewer-list">
          {load.items.map((item) => (
            <li key={item.interviewId}>
              <div>
                <strong>{item.candidateName || "Candidate"}</strong>
                <p>
                  {item.candidateEmail}
                  {item.status ? ` · ${item.status}` : ""}
                  {formatWhen(item.createdAt || item.startsAt)
                    ? ` · ${formatWhen(item.createdAt || item.startsAt)}`
                    : ""}
                </p>
              </div>
              {item.candidatePath ? (
                <button
                  type="button"
                  className="button secondary"
                  onClick={() =>
                    void copyPath(item.interviewId, item.candidatePath!)
                  }
                >
                  {copiedId === item.interviewId ? "Copied" : "Copy link"}
                </button>
              ) : (
                <span className="saved-interviewers-muted">Link unavailable</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="admin-page-actions" style={{ marginTop: 16 }}>
        <button className="button secondary" type="button" onClick={refresh}>
          Refresh
        </button>
      </div>
    </section>
  );
}
