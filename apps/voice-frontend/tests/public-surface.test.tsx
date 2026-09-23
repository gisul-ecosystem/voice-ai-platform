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

  it("keeps a human review entry point on the interviewer home", async () => {
    const { default: InterviewerPage } = await import("@/app/interviewer/page");
    const { render, screen } = await import("@testing-library/react");
    render(<InterviewerPage />);
    expect(screen.getByRole("link", { name: "Review a scorecard" })).toHaveAttribute(
      "href",
      "/interviewer/results",
    );
    expect(screen.getByRole("link", { name: "Create an interview" })).toHaveAttribute(
      "href",
      "/interviewer/admin/design",
    );
  });

  it("redirects legacy admin and setup entries to the design wizard", async () => {
    const { default: AdminPage } = await import("@/app/interviewer/admin/page");
    AdminPage();
    expect(redirect).toHaveBeenCalledWith("/interviewer/admin/design");

    redirect.mockClear();
    const { default: SetupPage } = await import("@/app/interviewer/setup/page");
    SetupPage();
    expect(redirect).toHaveBeenCalledWith("/interviewer/admin/design");
  });
});
