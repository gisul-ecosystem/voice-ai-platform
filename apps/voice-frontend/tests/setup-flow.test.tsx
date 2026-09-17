import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SetupForm } from "@/components/SetupForm";
import { getProduct } from "@/lib/products";

describe("setup to prejoin flow", () => {
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
    fireEvent.change(screen.getByLabelText("Interview length"), {
      target: { value: "15" },
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
        durationMinutes: 15,
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

});
