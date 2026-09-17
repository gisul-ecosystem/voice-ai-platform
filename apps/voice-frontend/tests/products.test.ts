import { describe, expect, it } from "vitest";

import { getProduct, products } from "@/lib/products";

describe("product registry", () => {
  it("registers only the supported public products", () => {
    expect(Object.keys(products)).toEqual(["interviewer", "customer-support"]);
  });

  it("keeps worker implementation names out of browser configuration", () => {
    expect(JSON.stringify(products)).not.toContain("aaptor");
    expect(JSON.stringify(products)).not.toContain("racko");
  });

  it("uses interview context while camera remains feature-gated", () => {
    expect(getProduct("interviewer").requiresInterviewContext).toBe(true);
    expect(getProduct("interviewer").cameraAllowed).toBe(false);
    expect(getProduct("interviewer").cameraEnabledByDefault).toBe(false);
    expect(getProduct("customer-support").requiresInterviewContext).toBe(false);
    expect(getProduct("customer-support").cameraAllowed).toBe(false);
    expect(getProduct("customer-support").cameraEnabledByDefault).toBe(false);
  });
});
