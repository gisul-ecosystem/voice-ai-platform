import { CandidateAttendShell } from "@/components/CandidateAttendShell";

export default async function AttendInterviewPage({
  searchParams,
}: {
  searchParams: Promise<{ invitation?: string }>;
}) {
  const { invitation } = await searchParams;
  return <CandidateAttendShell invitationToken={invitation} />;
}
