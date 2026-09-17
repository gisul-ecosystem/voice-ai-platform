import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CandidatePreview } from "@/components/CandidatePreview";

describe("candidate preview", () => {
  it("requires every enabled disclosure before device access", () => {
    const onContinue = vi.fn();
    render(
      <CandidatePreview
        request={{
          productId: "interviewer",
          participantName: "Priya",
          interviewSetup: {
            title: "Backend interview",
            role: "Backend Engineer",
            seniority: "mid",
            difficulty: "applied",
            durationMinutes: 30,
            language: "English",
            competencies: ["Problem solving"],
            maxProbesPerPhase: 2,
            monitoringEnabled: true,
            recordingEnabled: false,
          },
        }}
        onBack={vi.fn()}
        onContinue={onContinue}
      />,
    );

    const continueButton = screen.getByRole("button", {
      name: "Continue to device check",
    });
    expect(continueButton).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/conducted by an AI system/i));
    fireEvent.click(screen.getByLabelText(/agree to transcription/i));
    expect(continueButton).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/listen silently/i));
    expect(continueButton).toBeEnabled();
    fireEvent.click(continueButton);
    expect(onContinue).toHaveBeenCalledOnce();
  });
});
