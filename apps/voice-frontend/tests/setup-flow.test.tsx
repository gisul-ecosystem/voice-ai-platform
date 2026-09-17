import { fireEvent, render, screen } from "@testing-library/react";
import { transitionVoiceFlow } from "@gisul/voice-ui";
import { describe, expect, it, vi } from "vitest";

import { SetupForm } from "@/components/SetupForm";
import { getProduct } from "@/lib/products";

describe("setup to prejoin flow", () => {
  it("moves from setup to prejoin only on the expected event", () => {
    expect(transitionVoiceFlow("setup", "connected")).toBe("setup");
    expect(transitionVoiceFlow("setup", "setup-submitted")).toBe("preview");
    expect(transitionVoiceFlow("preview", "preview-confirmed")).toBe("prejoin");
  });

  it("collects required interviewer context", () => {
    const onContinue = vi.fn();
    render(
      <SetupForm
        product={getProduct("interviewer")}
        onContinue={onContinue}
      />,
    );

    fireEvent.change(screen.getByLabelText("Role"), {
      target: { value: "Backend Engineer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    fireEvent.change(screen.getByLabelText("Job description"), {
      target: { value: "Backend engineer" },
    });
    fireEvent.change(screen.getByLabelText("Candidate resume"), {
      target: { value: "Five years in Python" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and continue" }));
    fireEvent.change(screen.getByLabelText("Candidate name"), {
      target: { value: "Priya" },
    });
    fireEvent.change(screen.getByLabelText("Candidate email"), {
      target: { value: "priya@example.com" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Review interview" }),
    );
    expect(
      screen.getByRole("heading", { name: "Confirm the interview" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Schedule interview" }));

    expect(onContinue).toHaveBeenCalledWith(expect.objectContaining({
      productId: "interviewer",
      participantName: "Priya",
      candidateEmail: "priya@example.com",
      jobDescription: "Backend engineer",
      resumeText: "Five years in Python",
      interviewSetup: {
        title: "Structured interview",
        role: "Backend Engineer",
        seniority: "mid",
        difficulty: "applied",
        durationMinutes: 30,
        language: "English",
        competencies: [
          "Problem solving",
          "Role expertise",
          "Communication",
        ],
        maxProbesPerPhase: 2,
        monitoringEnabled: true,
        recordingEnabled: false,
      },
    }));
  });

  it("omits interview context from support setup", () => {
    render(
      <SetupForm
        product={getProduct("customer-support")}
        onContinue={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("Job description")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Resume text")).not.toBeInTheDocument();
  });
});
