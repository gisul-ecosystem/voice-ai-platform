"use client";

export default function AttendInterviewError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="attend-error-page">
      <section className="attend-error-card" role="alert">
        <span className="completion-mark" aria-hidden="true">
          !
        </span>
        <h1>The interview page could not continue</h1>
        <p>
          Keep this invitation open, check your connection, and retry the
          current step.
        </p>
        {error?.message ? (
          <p className="form-note" role="status">
            {error.message}
          </p>
        ) : null}
        <div className="button-row">
          <button className="button primary" type="button" onClick={reset}>
            Retry interview
          </button>
          <a className="button secondary" href="/interviewer">
            Return home
          </a>
        </div>
      </section>
    </main>
  );
}
