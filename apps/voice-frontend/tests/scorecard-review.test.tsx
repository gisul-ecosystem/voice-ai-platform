import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ sessionId: "ses_review01" }),
  useRouter: () => ({ push }),
}));

describe("scorecard review surface", () => {
  beforeEach(() => {
    push.mockClear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            session_id: "ses_review01",
            definition_id: "idef_live_quality_be_01",
            overall_recommendation: "insufficient_evidence",
            human_review_status: "pending",
            next_human_questions: ["Ask what the candidate personally handled."],
            competencies: [
              {
                competency_id: "problem_solving",
                rating: null,
                outcome: "not_assessed",
                excerpts: [],
                missing_intents: ["establish_ownership"],
                missing_evidence: ["personal contribution"],
              },
            ],
            quality_metrics: {
              mandatory_coverage_pct: 0,
              not_assessed_rate: 1,
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows coverage, missing intents, and requires a reason to override", async () => {
    const { default: ScorecardReviewPage } = await import(
      "@/app/interviewer/sessions/[sessionId]/scorecard/page"
    );
    render(<ScorecardReviewPage />);

    await waitFor(() => {
      expect(screen.getByText("problem solving")).toBeInTheDocument();
    });
    expect(screen.getByText(/Missing intents: establish_ownership/)).toBeInTheDocument();
    expect(screen.getByText(/Missing evidence: personal contribution/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept scorecard" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Override with reason" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter who is reviewing this scorecard.");

    fireEvent.change(screen.getByPlaceholderText("you@company.com"), {
      target: { value: "recruiter@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Override with reason" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "A reason is required to override this scorecard.",
    );
  });

  it("opens a scorecard from the lookup page", async () => {
    const { default: ScorecardLookupPage } = await import(
      "@/app/interviewer/results/page"
    );
    render(<ScorecardLookupPage />);
    fireEvent.change(screen.getByLabelText("Session id"), {
      target: { value: "ses_review01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open scorecard" }));
    expect(push).toHaveBeenCalledWith("/interviewer/sessions/ses_review01/scorecard");
  });
});
