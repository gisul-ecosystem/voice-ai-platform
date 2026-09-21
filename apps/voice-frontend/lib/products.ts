export type ProductId = "interviewer";

export type ProductConfig = {
  id: ProductId;
  participantLabel: string;
  joinLabel: string;
  cameraAllowed: boolean;
  cameraEnabledByDefault: boolean;
};

export const products: Record<ProductId, ProductConfig> = {
  interviewer: {
    id: "interviewer",
    participantLabel: "Candidate name",
    joinLabel: "Start interview",
    cameraAllowed: true,
    cameraEnabledByDefault: true,
  },
};

export function getProduct(productId: ProductId): ProductConfig {
  return products[productId];
}
