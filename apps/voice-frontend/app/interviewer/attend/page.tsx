import { redirect } from "next/navigation";

import { CandidateShell } from "@/components/interviewer/CandidateShell";

/**
 * Legacy join URL. Prefer `/interview/invite/{token}`.
 * Redirect when a token is present; otherwise show a short empty state.
 */
export default async function AttendInterviewPage({
  searchParams,
}: {
  searchParams: Promise<{ invitation?: string | string[] }>;
}) {
  const params = await searchParams;
  const invitationRaw = params.invitation;
  const invitation = Array.isArray(invitationRaw)
    ? invitationRaw[0]
    : invitationRaw;
  const invitationToken =
    typeof invitation === "string" && invitation.trim()
      ? invitation.trim()
      : undefined;

  if (invitationToken) {
    redirect(`/interview/invite/${encodeURIComponent(invitationToken)}`);
  }

  return (
    <CandidateShell title="Invitation required" lead="Open the complete link provided by the inviting organization.">
      <div className="center-state">
        <h2>Invitation required</h2>
        <p>Use the secure invite link from your recruiter.</p>
      </div>
    </CandidateShell>
  );
}
