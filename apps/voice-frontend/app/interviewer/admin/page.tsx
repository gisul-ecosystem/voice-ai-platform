import { redirect } from "next/navigation";

/** Canonical recruiter create path starts at design. */
export default function AdminInterviewPage() {
  redirect("/interviewer/admin/design");
}
