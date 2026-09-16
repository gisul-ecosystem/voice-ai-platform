import { VoiceDemo } from "@/components/VoiceDemo";
import { getProduct } from "@/lib/products";

export default function InterviewerPage() {
  return <VoiceDemo product={getProduct("interviewer")} />;
}
