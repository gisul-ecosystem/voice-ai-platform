export type ProductId = "interviewer" | "customer-support";

export type ProductConfig = {
  id: ProductId;
  href: "/interviewer" | "/support";
  eyebrow: string;
  title: string;
  description: string;
  participantLabel: string;
  joinLabel: string;
  requiresInterviewContext: boolean;
  cameraEnabledByDefault: boolean;
};

export const products: Record<ProductId, ProductConfig> = {
  interviewer: {
    id: "interviewer",
    href: "/interviewer",
    eyebrow: "AI Interview Agent",
    title: "AI Interviewer",
    description:
      "Run a structured voice and video interview using role and candidate context.",
    participantLabel: "Candidate name",
    joinLabel: "Start interview",
    requiresInterviewContext: true,
    cameraEnabledByDefault: true,
  },
  "customer-support": {
    id: "customer-support",
    href: "/support",
    eyebrow: "AI Support Agent",
    title: "Customer Support",
    description:
      "Try a voice support conversation with contextual answers and service tools.",
    participantLabel: "Your name",
    joinLabel: "Start support call",
    requiresInterviewContext: false,
    cameraEnabledByDefault: false,
  },
};

export function getProduct(productId: ProductId): ProductConfig {
  return products[productId];
}
