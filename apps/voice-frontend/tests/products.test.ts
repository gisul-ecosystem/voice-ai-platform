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

  it("uses interview context and camera only where needed", () => {
    expect(getProduct("interviewer").requiresInterviewContext).toBe(true);
    expect(getProduct("interviewer").cameraEnabledByDefault).toBe(true);
    expect(getProduct("customer-support").requiresInterviewContext).toBe(false);
    expect(getProduct("customer-support").cameraEnabledByDefault).toBe(false);
  });
});
