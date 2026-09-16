import { VoiceDemo } from "@/components/VoiceDemo";
import { getProduct } from "@/lib/products";

export default function SupportPage() {
  return <VoiceDemo product={getProduct("customer-support")} />;
}
