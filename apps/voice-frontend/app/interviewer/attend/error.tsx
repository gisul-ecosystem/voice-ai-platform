"use client";

export default function AttendInterviewError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="demo-page demo-stage-candidate">
      <section className="demo-card">
        <div className="center-state" role="alert">
          <span className="completion-mark" aria-hidden="true">!</span>
          <h1>The interview page could not continue</h1>
          <p>
            Keep this invitation open, check your connection, and retry the
            current step.
          </p>
          <button className="button primary" type="button" onClick={reset}>
            Retry interview
          </button>
        </div>
      </section>
    </main>
  );
}
