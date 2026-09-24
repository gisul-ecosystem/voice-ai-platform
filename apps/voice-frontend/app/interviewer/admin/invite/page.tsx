"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";

import {
  EMPTY_ROLE_DRAFT,
  getRoleDraftSnapshot,
  subscribeRoleDraft,
} from "@/lib/interviewer/role-draft";

/** Legacy invite wizard — send users to the template hub. */
export default function InviteCandidatesPage() {
  const router = useRouter();
  const draftBundle = useSyncExternalStore(
    subscribeRoleDraft,
    getRoleDraftSnapshot,
    () => EMPTY_ROLE_DRAFT,
  );

  useEffect(() => {
    const published = draftBundle.state?.published as
      | Record<string, unknown>
      | undefined;
    const definitionId = String(
      published?.definition_id || draftBundle.state?.definitionId || "",
    ).trim();
    if (definitionId.length >= 8) {
      router.replace(
        `/interviewer/templates/${encodeURIComponent(definitionId)}`,
      );
      return;
    }
    router.replace("/interviewer");
  }, [draftBundle, router]);

  return (
    <main className="interviewer-home admin-builder-page">
      <div className="center-state">
        <h2>Opening template…</h2>
      </div>
    </main>
  );
}
