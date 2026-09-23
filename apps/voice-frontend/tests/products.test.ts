import { describe, expect, it } from "vitest";

import { getProduct, products } from "@/lib/products";

describe("product registry", () => {
  it("registers only the supported public products", () => {
    expect(Object.keys(products)).toEqual(["interviewer"]);
  });

  it("keeps worker implementation names out of browser configuration", () => {
    expect(JSON.stringify(products)).not.toContain("aaptor");
    expect(JSON.stringify(products)).not.toContain("racko");
  });

  it("enables LiveKit camera for interviewer sessions", () => {
    expect(getProduct("interviewer").cameraAllowed).toBe(true);
    expect(getProduct("interviewer").cameraEnabledByDefault).toBe(true);
  });
});
