import { CandidateShell } from "@/components/interviewer/CandidateShell";
import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

export default async function CandidateInvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const invitationToken = decodeURIComponent(token || "").trim();

  return (
    <CandidateShell lockNavigation>
      {invitationToken ? (
        <CandidateInterviewJourney invitationToken={invitationToken} />
      ) : (
        <div className="center-state">
          <h2>Invitation required</h2>
          <p>Open the complete link provided by the inviting organization.</p>
        </div>
      )}
    </CandidateShell>
  );
}
