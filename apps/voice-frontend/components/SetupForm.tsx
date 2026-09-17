"use client";

import { useEffect, useState, type FormEvent } from "react";

import type { ProductConfig } from "@/lib/products";
import {
  INTERVIEW_DURATION_OPTIONS,
  normalizeInterviewDuration,
  type PublicSessionRequest,
} from "@/lib/session-contract";

type SetupFormProps = {
  product: ProductConfig;
  initialValue?: PublicSessionRequest;
  onContinue: (value: PublicSessionRequest) => void;
};

const DRAFT_KEY = "ai-interviewer:setup-draft";
const setupSteps = ["Role & format", "Interview content", "Candidate & policy"];
const stepDescriptions = [
  "Define the role, seniority and shape of the conversation.",
  "Give the interviewer the evidence and competencies it should use.",
  "Set the schedule, candidate details and consent policy.",
];

function defaultStartTime(): string {
  const date = new Date(Date.now() + 10 * 60_000);
  date.setSeconds(0, 0);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function SetupForm({
  product,
  initialValue,
  onContinue,
}: SetupFormProps) {
  const [participantName, setParticipantName] = useState(
    initialValue?.participantName ?? "",
  );
  const [jobDescription, setJobDescription] = useState(
    initialValue?.jobDescription ?? "",
  );
  const [resumeText, setResumeText] = useState(
    initialValue?.resumeText ?? "",
  );
  const initialSetup = initialValue?.interviewSetup;
  const [step, setStep] = useState(0);
  const [reviewing, setReviewing] = useState(false);
  const [hydrated, setHydrated] = useState(Boolean(initialValue));
  const [title, setTitle] = useState(initialSetup?.title ?? "Structured interview");
  const [role, setRole] = useState(initialSetup?.role ?? "");
  const [seniority, setSeniority] = useState(initialSetup?.seniority ?? "mid");
  const [difficulty, setDifficulty] = useState(
    initialSetup?.difficulty ?? "applied",
  );
  const [durationMinutes, setDurationMinutes] = useState(
    normalizeInterviewDuration(initialSetup?.durationMinutes),
  );
  const [language, setLanguage] = useState(initialSetup?.language ?? "English");
  const [competencies, setCompetencies] = useState(
    initialSetup?.competencies.join(", ") ??
      "Problem solving, Role expertise, Communication",
  );
  const [maxProbesPerPhase, setMaxProbesPerPhase] = useState(
    initialSetup?.maxProbesPerPhase ?? 2,
  );
  const [monitoringEnabled, setMonitoringEnabled] = useState(
    initialSetup?.monitoringEnabled ?? true,
  );
  const [recordingEnabled, setRecordingEnabled] = useState(
    initialSetup?.recordingEnabled ?? false,
  );
  const [candidateEmail, setCandidateEmail] = useState(
    initialValue?.candidateEmail ?? "",
  );
  const [startsAt, setStartsAt] = useState(
    initialValue?.startsAt
      ? new Date(initialValue.startsAt).toISOString().slice(0, 16)
      : defaultStartTime(),
  );
  const timezone =
    initialValue?.timezone ??
    Intl.DateTimeFormat().resolvedOptions().timeZone ??
    "UTC";

  useEffect(() => {
    if (initialValue) return;
    const timer = window.setTimeout(() => {
      try {
        const saved = sessionStorage.getItem(DRAFT_KEY);
        if (!saved) return;
        const draft = JSON.parse(saved) as PublicSessionRequest;
        const setup = draft.interviewSetup;
        setParticipantName(draft.participantName || "");
        setCandidateEmail(draft.candidateEmail || "");
        setJobDescription(draft.jobDescription || "");
        setResumeText(draft.resumeText || "");
        if (draft.startsAt) {
          const date = new Date(draft.startsAt);
          const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
          setStartsAt(local.toISOString().slice(0, 16));
        }
        if (setup) {
          setTitle(setup.title);
          setRole(setup.role);
          setSeniority(setup.seniority);
          setDifficulty(setup.difficulty);
          setDurationMinutes(setup.durationMinutes);
          setLanguage(setup.language);
          setCompetencies(setup.competencies.join(", "));
          setMaxProbesPerPhase(setup.maxProbesPerPhase);
          setMonitoringEnabled(setup.monitoringEnabled);
          setRecordingEnabled(setup.recordingEnabled);
        }
      } catch {
        sessionStorage.removeItem(DRAFT_KEY);
      } finally {
        setHydrated(true);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [initialValue]);

  useEffect(() => {
    if (!hydrated || !product.requiresInterviewContext) return;
    sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({
        productId: product.id,
        participantName,
        candidateEmail,
        startsAt: startsAt ? new Date(startsAt).toISOString() : undefined,
        timezone,
        jobDescription,
        resumeText,
        interviewSetup: {
          title,
          role,
          seniority,
          difficulty,
          durationMinutes,
          language,
          competencies: competencies
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
          maxProbesPerPhase,
          monitoringEnabled,
          recordingEnabled,
        },
      } satisfies PublicSessionRequest),
    );
  }, [
    candidateEmail,
    competencies,
    difficulty,
    durationMinutes,
    hydrated,
    jobDescription,
    language,
    maxProbesPerPhase,
    monitoringEnabled,
    participantName,
    product.id,
    product.requiresInterviewContext,
    recordingEnabled,
    resumeText,
    role,
    seniority,
    startsAt,
    timezone,
    title,
  ]);

  function buildValue(): PublicSessionRequest {
    return {
      productId: product.id,
      participantName: participantName.trim(),
      jobDescription: jobDescription.trim() || undefined,
      resumeText: resumeText.trim() || undefined,
      candidateEmail: candidateEmail.trim() || undefined,
      startsAt: startsAt ? new Date(startsAt).toISOString() : undefined,
      timezone,
      interviewSetup: product.requiresInterviewContext
        ? {
            title: title.trim(),
            role: role.trim(),
            seniority,
            difficulty,
            durationMinutes,
            language: language.trim(),
            competencies: competencies
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
            maxProbesPerPhase,
            monitoringEnabled,
            recordingEnabled,
          }
        : undefined,
    };
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (product.requiresInterviewContext && step < 2) {
      setStep((current) => current + 1);
      return;
    }
    if (product.requiresInterviewContext && !reviewing) {
      setReviewing(true);
      return;
    }
    onContinue(buildValue());
  }

  if (!product.requiresInterviewContext) {
    return (
      <form className="setup-form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="participant-name">{product.participantLabel}</label>
          <input
            id="participant-name"
            autoComplete="name"
            maxLength={120}
            required
            value={participantName}
            onChange={(event) => setParticipantName(event.target.value)}
            placeholder="Enter a display name"
          />
        </div>
        <p className="form-note">
          No account credentials are needed for this internal support demo.
        </p>
        <button className="button primary" type="submit">
          Continue to device check
        </button>
      </form>
    );
  }

  return (
    <form className="setup-form interview-setup-form" onSubmit={submit}>
      <aside className="setup-rail">
        <div>
          <p className="step-label">Interview setup</p>
          <h2>Build the interview</h2>
          <p className="setup-rail-intro">
            Complete each section, then review everything before scheduling.
          </p>
        </div>
        <ol className="setup-progress" aria-label="Interview setup progress">
          {setupSteps.map((label, index) => {
            const complete = index < step || reviewing;
            const active = index === step && !reviewing;
            return (
              <li className={active ? "active" : complete ? "complete" : ""}
                key={label}>
                <button
                  type="button"
                  disabled={index > step && !reviewing}
                  aria-current={active ? "step" : undefined}
                  onClick={() => {
                    setStep(index);
                    setReviewing(false);
                  }}
                >
                  <span>{complete ? "✓" : index + 1}</span>
                  <div>
                    <strong>{label}</strong>
                    <small>{complete ? "Complete" : active ? "In progress" : "Not started"}</small>
                  </div>
                </button>
              </li>
            );
          })}
          <li className={reviewing ? "active" : ""}>
            <span className="progress-review-number">4</span>
            <div>
              <strong>Review & schedule</strong>
              <small>{reviewing ? "Ready to schedule" : "Final check"}</small>
            </div>
          </li>
        </ol>
        <div className="setup-rail-summary">
          <span>Current interview</span>
          <strong>{role.trim() || "Role not set"}</strong>
          <p>{durationMinutes} min · {language} · {seniority}</p>
        </div>
        <p className="draft-status">
          <span aria-hidden="true">✓</span> Draft saved in this browser
        </p>
      </aside>

      <section className="setup-panel">
        <header className="setup-panel-heading">
          <div>
            <p className="step-label">
              {reviewing ? "Final review" : `Step ${step + 1} of 3`}
            </p>
            <h2>{reviewing ? "Review and schedule" : setupSteps[step]}</h2>
            <p>
              {reviewing
                ? "Confirm the candidate experience and schedule before creating the invitation."
                : stepDescriptions[step]}
            </p>
          </div>
          <span className="step-count">{reviewing ? "4 / 4" : `${step + 1} / 4`}</span>
        </header>

        <div className="setup-fields">

      {step === 0 && !reviewing ? (
        <>
          <div className="field">
            <label htmlFor="interview-title">Interview title</label>
            <p className="field-help">Shown to the candidate on their invitation.</p>
            <input id="interview-title" required maxLength={160} value={title}
              onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="role">Role</label>
            <p className="field-help">Use the exact position being assessed.</p>
            <input id="role" required maxLength={160} value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="Backend Engineer" />
          </div>
          <div className="field">
            <label htmlFor="seniority">Seniority</label>
            <p className="field-help">Sets the expected depth of answers.</p>
            <select id="seniority" value={seniority}
              onChange={(event) => setSeniority(event.target.value)}>
              <option value="intern">Intern</option>
              <option value="junior">Junior</option>
              <option value="mid">Mid-level</option>
              <option value="senior">Senior</option>
              <option value="lead">Lead</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="difficulty">Question complexity</label>
            <p className="field-help">Controls how questions move from theory to judgment.</p>
            <select id="difficulty" value={difficulty}
              onChange={(event) => setDifficulty(event.target.value)}>
              <option value="foundational">Foundational</option>
              <option value="applied">Applied</option>
              <option value="diagnostic">Diagnostic</option>
              <option value="strategic">Strategic</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="duration">Interview length</label>
            <p className="field-help">Choose 15, 30, or 45 minutes.</p>
            <select
              id="duration"
              value={durationMinutes}
              onChange={(event) =>
                setDurationMinutes(normalizeInterviewDuration(Number(event.target.value)))
              }
            >
              {INTERVIEW_DURATION_OPTIONS.map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} minutes
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="language">Interview language</label>
            <p className="field-help">The interviewer will ask questions in this language.</p>
            <input id="language" required maxLength={32} value={language}
              onChange={(event) => setLanguage(event.target.value)} />
          </div>
        </>
      ) : null}

      {step === 1 && !reviewing ? (
        <>
          <div className="field field-document">
            <label htmlFor="job-description">Job description</label>
            <p className="field-help">
              Paste responsibilities, required skills and success criteria.
            </p>
            <textarea id="job-description" required rows={5}
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              placeholder="Paste role responsibilities and requirements" />
          </div>
          <div className="field field-document">
            <label htmlFor="resume-text">Candidate resume</label>
            <p className="field-help">
              Used to personalize evidence-based questions and follow-ups.
            </p>
            <textarea id="resume-text" required rows={5}
              value={resumeText}
              onChange={(event) => setResumeText(event.target.value)}
              placeholder="Paste the candidate resume text" />
          </div>
          <div className="field">
            <label htmlFor="competencies">Competencies (comma-separated)</label>
            <p className="field-help">
              Focus the interview on three to six measurable areas.
            </p>
            <input id="competencies" required value={competencies}
              onChange={(event) => setCompetencies(event.target.value)}
              placeholder="Problem solving, Python, Communication" />
          </div>
          <div className="field">
            <label htmlFor="probe-depth">Maximum follow-ups per phase</label>
            <p className="field-help">
              More follow-ups improve depth but require additional interview time.
            </p>
            <select id="probe-depth" value={maxProbesPerPhase}
              onChange={(event) => setMaxProbesPerPhase(Number(event.target.value))}>
              <option value={0}>None</option>
              <option value={1}>1 follow-up</option>
              <option value={2}>2 follow-ups</option>
              <option value={3}>3 follow-ups</option>
            </select>
          </div>
        </>
      ) : null}

      {step === 2 && !reviewing ? (
        <>
          <div className="field">
            <label htmlFor="participant-name">{product.participantLabel}</label>
            <p className="field-help">Displayed inside the interview room.</p>
            <input id="participant-name" autoComplete="name" maxLength={120}
              required
              value={participantName}
              onChange={(event) => setParticipantName(event.target.value)}
              placeholder="Enter the candidate name" />
          </div>
          <div className="field">
            <label htmlFor="candidate-email">Candidate email</label>
            <p className="field-help">Used by the integrating product to send the invitation.</p>
            <input id="candidate-email" type="email" autoComplete="email"
              maxLength={320} required value={candidateEmail}
              onChange={(event) => setCandidateEmail(event.target.value)}
              placeholder="candidate@example.com" />
          </div>
          <div className="field">
            <label htmlFor="starts-at">Scheduled start</label>
            <p className="field-help">Candidates can join up to 15 minutes early.</p>
            <input id="starts-at" type="datetime-local" required value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="timezone">Timezone</label>
            <p className="field-help">Detected from this browser.</p>
            <input id="timezone" readOnly value={timezone} />
          </div>
          <fieldset className="policy-list field-wide">
            <legend>Candidate experience policy</legend>
            <label className="policy-option">
              <input type="checkbox" checked={monitoringEnabled}
                onChange={(event) => setMonitoringEnabled(event.target.checked)} />
              <span>
                <strong>Human monitoring</strong>
                <small>Allow an authorized reviewer to listen silently after disclosure.</small>
              </span>
            </label>
            <label className="policy-option">
              <input type="checkbox" checked={recordingEnabled}
                onChange={(event) => setRecordingEnabled(event.target.checked)} />
              <span>
                <strong>Session recording</strong>
                <small>Record the interview only after explicit candidate consent.</small>
              </span>
            </label>
            <p className="policy-note">
              AI interviewing and transcription are disclosed before device
              access. Candidates must also receive an accommodation path.
            </p>
          </fieldset>
        </>
      ) : null}

      {reviewing ? (
        <section className="setup-review" aria-labelledby="setup-review-title">
          <h3 id="setup-review-title" className="sr-only">Confirm the interview</h3>
          <div className="review-grid">
            <article>
              <span>Interview</span>
              <strong>{title}</strong>
              <p>{role} · {seniority} · {difficulty}</p>
            </article>
            <article>
              <span>Format</span>
              <strong>{durationMinutes} minutes · {language}</strong>
              <p>Up to {maxProbesPerPhase} follow-ups per phase</p>
            </article>
            <article>
              <span>Candidate</span>
              <strong>{participantName}</strong>
              <p>{candidateEmail}</p>
            </article>
            <article>
              <span>Schedule</span>
              <strong>{new Date(startsAt).toLocaleString()}</strong>
              <p>{timezone}</p>
            </article>
          </div>
          <div className="review-detail">
            <div>
              <span>Competencies</span>
              <p>{competencies}</p>
            </div>
            <div>
              <span>Candidate policy</span>
              <p>
                AI and transcription disclosed · Monitoring{" "}
                {monitoringEnabled ? "enabled" : "disabled"} · Recording{" "}
                {recordingEnabled ? "enabled" : "disabled"}
              </p>
            </div>
          </div>
        </section>
      ) : null}

        </div>
      <div className="setup-actions">
        {step > 0 || reviewing ? (
          <button
            className="button secondary"
            type="button"
            onClick={() => {
              if (reviewing) setReviewing(false);
              else setStep((current) => current - 1);
            }}
          >
            {reviewing ? "Edit details" : "Back"}
          </button>
        ) : <span />}
        <button className="button primary" type="submit">
          {reviewing ? "Schedule interview" : step < 2 ? "Save and continue" : "Review interview"}
        </button>
      </div>
      </section>
    </form>
  );
}
