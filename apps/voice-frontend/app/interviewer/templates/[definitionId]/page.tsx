"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { LandingNav, TemplateHubNav } from "@/components/interviewer/LandingNav";
import { TemplateInviteForm } from "@/components/interviewer/TemplateInviteForm";
import { TemplateInvitesList } from "@/components/interviewer/TemplateInvitesList";
import { TemplateResultsLookup } from "@/components/interviewer/TemplateResultsLookup";
import {
  roleDraftFromSavedDefinition,
  summaryFromDefinitionDetail,
  writeRoleDraft,
  type RoleDraftState,
  type SavedDefinitionSummary,
} from "@/lib/interviewer/role-draft";

type HubTab = "invite" | "invites" | "results";

function parseTab(value: string | null): HubTab {
  if (value === "invites" || value === "results") return value;
  return "invite";
}

function TemplateHubInner() {
  const params = useParams<{ definitionId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const definitionId = decodeURIComponent(params.definitionId || "").trim();
  const tab = parseTab(searchParams.get("tab"));
  const invalidId = definitionId.length < 8;

  const [summary, setSummary] = useState<SavedDefinitionSummary | null>(null);
  const [draft, setDraft] = useState<RoleDraftState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!invalidId);
  const [inviteRefresh, setInviteRefresh] = useState(0);

  useEffect(() => {
    if (invalidId) return;
    let cancelled = false;
    fetch(`/api/admin/definitions/${encodeURIComponent(definitionId)}`)
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(
            String(data.error || "Interview template not found."),
          );
        }
        const mapped = summaryFromDefinitionDetail(
          data as Record<string, unknown>,
        );
        if (!mapped) {
          throw new Error("Interview template not found.");
        }
        const nextDraft = roleDraftFromSavedDefinition(mapped);
        writeRoleDraft(nextDraft);
        if (!cancelled) {
          setSummary(mapped);
          setDraft(nextDraft);
          setError("");
          setLoading(false);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setSummary(null);
          setDraft(null);
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load template.",
          );
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [definitionId, invalidId]);

  const title = useMemo(
    () => summary?.title || "Interview template",
    [summary],
  );

  function setTab(next: HubTab) {
    const query = next === "invite" ? "" : `?tab=${next}`;
    router.replace(
      `/interviewer/templates/${encodeURIComponent(definitionId)}${query}`,
    );
  }

  return (
    <main className="interviewer-home template-hub-page">
      <LandingNav
        ariaLabel="Template hub navigation"
        trailing={
          <>
            <Link href="/interviewer">All templates</Link>
            <Link className="button secondary" href="/interviewer/admin/design">
              New template
            </Link>
          </>
        }
      />
      {invalidId ? (
        <div className="center-state">
          <h2>Template unavailable</h2>
          <p>Invalid template id.</p>
          <Link className="button primary" href="/interviewer">
            Back to templates
          </Link>
        </div>
      ) : null}
      {!invalidId && loading ? (
        <div className="center-state">
          <h2>Loading template…</h2>
        </div>
      ) : null}
      {!invalidId && !loading && error ? (
        <div className="center-state">
          <h2>Template unavailable</h2>
          <p>{error}</p>
          <Link className="button primary" href="/interviewer">
            Back to templates
          </Link>
        </div>
      ) : null}
      {!invalidId && !loading && !error && summary && draft ? (
        <div className="template-hub">
          <header className="template-hub-header">
            <div>
              <p className="eyebrow">Template</p>
              <h1>{title}</h1>
              <ul className="template-meta" aria-label="Template details">
                <li>{summary.role}</li>
                <li>{summary.seniority}</li>
                <li>{summary.duration_minutes} min</li>
              </ul>
            </div>
            <TemplateHubNav
              definitionId={definitionId}
              current={tab}
              onNavigate={setTab}
            />
          </header>

          <div className="template-hub-panel">
            {tab === "invite" ? (
              <>
                <div className="template-hub-panel-intro">
                  <h2>Invite a candidate</h2>
                  <p>
                    Create a single-use link. They can join anytime while the
                    link is valid.
                  </p>
                </div>
                <TemplateInviteForm
                  definitionId={definitionId}
                  draft={draft}
                  onInvited={() => setInviteRefresh((value) => value + 1)}
                />
              </>
            ) : null}
            {tab === "invites" ? (
              <TemplateInvitesList
                definitionId={definitionId}
                refreshKey={inviteRefresh}
              />
            ) : null}
            {tab === "results" ? <TemplateResultsLookup /> : null}
          </div>
        </div>
      ) : null}
    </main>
  );
}

export default function TemplateHubPage() {
  return (
    <Suspense
      fallback={
        <main className="interviewer-home template-hub-page">
          <div className="center-state">
            <h2>Loading template…</h2>
          </div>
        </main>
      }
    >
      <TemplateHubInner />
    </Suspense>
  );
}
