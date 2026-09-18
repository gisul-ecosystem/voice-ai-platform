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

  it("keeps camera access feature-gated", () => {
    expect(getProduct("interviewer").cameraAllowed).toBe(false);
    expect(getProduct("interviewer").cameraEnabledByDefault).toBe(false);
  });
});
