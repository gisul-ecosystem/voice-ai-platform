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
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.change(screen.getByLabelText("Job description"), {
      target: {
        value:
          "Backend engineer building APIs with Python, FastAPI, and ownership of production services.",
      },
    });
    fireEvent.change(screen.getByLabelText("Candidate resume"), {
      target: {
        value:
          "Five years in Python backends, FastAPI services, and on-call ownership for distributed systems.",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
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
      jobDescription:
        "Backend engineer building APIs with Python, FastAPI, and ownership of production services.",
      resumeText:
        "Five years in Python backends, FastAPI services, and on-call ownership for distributed systems.",
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

  it("blocks incomplete interview content before scheduling", () => {
    render(
      <SetupForm
        product={getProduct("interviewer")}
        onContinue={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Role"), {
      target: { value: "Backend Engineer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.change(screen.getByLabelText("Job description"), {
      target: { value: "too short" },
    });
    fireEvent.change(screen.getByLabelText("Candidate resume"), {
      target: { value: "also too short" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(
      screen.getByText(/Paste a complete job description/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Candidate name")).not.toBeInTheDocument();
  });

});
