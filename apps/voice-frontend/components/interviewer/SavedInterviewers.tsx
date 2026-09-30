"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { SavedDefinitionSummary } from "@/lib/interviewer/role-draft";

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
    fetch("/api/admin/definitions?limit=50")
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(String(data.error || "Could not load templates."));
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
                : "Could not load templates.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function openTemplate(item: SavedDefinitionSummary) {
    setBusyId(item.definition_id);
    router.push(
      `/interviewer/templates/${encodeURIComponent(item.definition_id)}`,
    );
  }

  return (
    <section className="template-library" aria-label="Interview templates">
      {load.status === "loading" ? (
        <div className="template-library-status" role="status">
          Loading templates…
        </div>
      ) : null}

      {load.status === "error" ? (
        <div className="template-library-status" role="alert">
          {load.message}
        </div>
      ) : null}

      {load.status === "ready" && load.items.length === 0 ? (
        <div className="template-empty">
          <p className="eyebrow">Get started</p>
          <h2>No templates yet</h2>
          <p>
            Design a role, align competencies, and publish once. Then invite as
            many candidates as you need from the same template.
          </p>
          <Link className="button primary" href="/interviewer/admin/design">
            Create your first template
          </Link>
        </div>
      ) : null}

      {load.status === "ready" && load.items.length > 0 ? (
        <ul className="template-list">
          {load.items.map((item) => {
            const busy = busyId === item.definition_id;
            return (
              <li key={item.definition_id}>
                <button
                  type="button"
                  className="template-row"
                  disabled={busy}
                  onClick={() => openTemplate(item)}
                >
                  <div className="template-row-main">
                    <strong>{item.title}</strong>
                    <p>
                      <span>{item.role}</span>
                      <span aria-hidden="true">·</span>
                      <span>{item.seniority}</span>
                      <span aria-hidden="true">·</span>
                      <span>{item.duration_minutes} min</span>
                      {formatPublishedAt(item.published_at) ? (
                        <>
                          <span aria-hidden="true">·</span>
                          <span>{formatPublishedAt(item.published_at)}</span>
                        </>
                      ) : null}
                    </p>
                  </div>
                  <span className="template-row-action">
                    {busy ? "Opening…" : "Open"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
