import { beforeEach, describe, expect, it, vi } from "vitest";

describe("public product surface", () => {
  const redirect = vi.fn();

  beforeEach(() => {
    vi.resetModules();
    redirect.mockClear();
    vi.doMock("next/navigation", () => ({ redirect }));
  });

  it("routes the public root directly to the interviewer", async () => {
    const { default: Home } = await import("@/app/page");
    Home();
    expect(redirect).toHaveBeenCalledWith("/interviewer");
  });

  it("does not expose the customer-support demo route", async () => {
    const { default: SupportPage } = await import("@/app/support/page");
    SupportPage();
    expect(redirect).toHaveBeenCalledWith("/interviewer");
  });
});
