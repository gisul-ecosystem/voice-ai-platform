import { redirect } from "next/navigation";

/** Legacy creator — redirect to the admin wizard. */
export default function InterviewSetupPage() {
  redirect("/interviewer/admin/design");
}
