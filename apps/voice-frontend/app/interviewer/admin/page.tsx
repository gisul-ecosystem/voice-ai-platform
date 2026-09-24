import { redirect } from "next/navigation";

/** Admin entry goes to the template library. */
export default function AdminInterviewPage() {
  redirect("/interviewer");
}
