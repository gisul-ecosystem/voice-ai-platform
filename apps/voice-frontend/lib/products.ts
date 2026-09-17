export type ProductId = "interviewer";

export type ProductConfig = {
  id: ProductId;
  participantLabel: string;
  joinLabel: string;
  cameraAllowed: boolean;
  cameraEnabledByDefault: boolean;
};

const interviewCameraEnabled =
  process.env.NEXT_PUBLIC_INTERVIEW_CAMERA_ENABLED === "true";

export const products: Record<ProductId, ProductConfig> = {
  interviewer: {
    id: "interviewer",
    participantLabel: "Candidate name",
    joinLabel: "Start interview",
    cameraAllowed: interviewCameraEnabled,
    cameraEnabledByDefault: false,
  },
};

export function getProduct(productId: ProductId): ProductConfig {
  return products[productId];
}
