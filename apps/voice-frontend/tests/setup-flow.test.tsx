import { fireEvent, render, screen } from "@testing-library/react";
import { transitionVoiceFlow } from "@gisul/voice-ui";
import { describe, expect, it, vi } from "vitest";

import { SetupForm } from "@/components/SetupForm";
import { getProduct } from "@/lib/products";

describe("setup to prejoin flow", () => {
  it("moves from setup to prejoin only on the expected event", () => {
    expect(transitionVoiceFlow("setup", "connected")).toBe("setup");
    expect(transitionVoiceFlow("setup", "setup-submitted")).toBe("prejoin");
  });

  it("collects required interviewer context", () => {
    const onContinue = vi.fn();
    render(
      <SetupForm
        product={getProduct("interviewer")}
        onContinue={onContinue}
      />,
    );

    fireEvent.change(screen.getByLabelText("Candidate name"), {
      target: { value: "Priya" },
    });
    fireEvent.change(screen.getByLabelText("Job description"), {
      target: { value: "Backend engineer" },
    });
    fireEvent.change(screen.getByLabelText("Resume text"), {
      target: { value: "Five years in Python" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to device check" }),
    );

    expect(onContinue).toHaveBeenCalledWith({
      productId: "interviewer",
      participantName: "Priya",
      jobDescription: "Backend engineer",
      resumeText: "Five years in Python",
    });
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
