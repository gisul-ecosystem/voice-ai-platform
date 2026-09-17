"use client";

import { useState, type FormEvent } from "react";

import type { ProductConfig } from "@/lib/products";
import type { PublicSessionRequest } from "@/lib/session-contract";

type SetupFormProps = {
  product: ProductConfig;
  initialValue?: PublicSessionRequest;
  onContinue: (value: PublicSessionRequest) => void;
};

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
  const [title, setTitle] = useState(initialSetup?.title ?? "Structured interview");
  const [role, setRole] = useState(initialSetup?.role ?? "");
  const [seniority, setSeniority] = useState(initialSetup?.seniority ?? "mid");
  const [difficulty, setDifficulty] = useState(
    initialSetup?.difficulty ?? "applied",
  );
  const [durationMinutes, setDurationMinutes] = useState(
    initialSetup?.durationMinutes ?? 30,
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

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (product.requiresInterviewContext && step < 2) {
      setStep((current) => current + 1);
      return;
    }
    onContinue({
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
    });
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
      <div className="setup-progress" aria-label="Interview setup progress">
        {["Role", "Interview design", "Candidate policy"].map((label, index) => (
          <span className={index === step ? "active" : ""} key={label}>
            {index + 1}. {label}
          </span>
        ))}
      </div>

      {step === 0 ? (
        <>
          <div className="field">
            <label htmlFor="interview-title">Interview title</label>
            <input id="interview-title" required maxLength={160} value={title}
              onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="role">Role</label>
            <input id="role" required maxLength={160} value={role}
              onChange={(event) => setRole(event.target.value)}
              placeholder="Backend Engineer" />
          </div>
          <div className="field">
            <label htmlFor="seniority">Seniority</label>
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
            <select id="difficulty" value={difficulty}
              onChange={(event) => setDifficulty(event.target.value)}>
              <option value="foundational">Foundational</option>
              <option value="applied">Applied</option>
              <option value="diagnostic">Diagnostic</option>
              <option value="strategic">Strategic</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="duration">Duration (minutes)</label>
            <input id="duration" type="number" min={10} max={120} required
              value={durationMinutes}
              onChange={(event) => setDurationMinutes(event.target.valueAsNumber)} />
          </div>
          <div className="field">
            <label htmlFor="language">Interview language</label>
            <input id="language" required maxLength={32} value={language}
              onChange={(event) => setLanguage(event.target.value)} />
          </div>
        </>
      ) : null}

      {step === 1 ? (
        <>
          <div className="field">
            <label htmlFor="job-description">Job description</label>
            <textarea id="job-description" required rows={5}
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              placeholder="Paste role responsibilities and requirements" />
          </div>
          <div className="field">
            <label htmlFor="resume-text">Candidate resume</label>
            <textarea id="resume-text" required rows={5}
              value={resumeText}
              onChange={(event) => setResumeText(event.target.value)}
              placeholder="Paste the candidate resume text" />
          </div>
          <div className="field field-wide">
            <label htmlFor="competencies">Competencies (comma-separated)</label>
            <input id="competencies" required value={competencies}
              onChange={(event) => setCompetencies(event.target.value)}
              placeholder="Problem solving, Python, Communication" />
          </div>
          <div className="field field-wide">
            <label htmlFor="probe-depth">Maximum follow-ups per phase</label>
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

      {step === 2 ? (
        <>
          <div className="field">
            <label htmlFor="participant-name">{product.participantLabel}</label>
            <input id="participant-name" autoComplete="name" maxLength={120}
              required
              value={participantName}
              onChange={(event) => setParticipantName(event.target.value)}
              placeholder="Enter the candidate name" />
          </div>
          <div className="field">
            <label htmlFor="candidate-email">Candidate email</label>
            <input id="candidate-email" type="email" autoComplete="email"
              maxLength={320} required value={candidateEmail}
              onChange={(event) => setCandidateEmail(event.target.value)}
              placeholder="candidate@example.com" />
          </div>
          <div className="field">
            <label htmlFor="starts-at">Scheduled start</label>
            <input id="starts-at" type="datetime-local" required value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="timezone">Timezone</label>
            <input id="timezone" readOnly value={timezone} />
          </div>
          <div className="policy-list field-wide">
            <label>
              <input type="checkbox" checked={monitoringEnabled}
                onChange={(event) => setMonitoringEnabled(event.target.checked)} />
              Allow disclosed listen-only human monitoring
            </label>
            <label>
              <input type="checkbox" checked={recordingEnabled}
                onChange={(event) => setRecordingEnabled(event.target.checked)} />
              Allow recording after explicit candidate consent
            </label>
            <p>
              AI interviewing and transcription are disclosed before device
              access. Candidates must also receive an accommodation path.
            </p>
          </div>
        </>
      ) : null}

      <div className="setup-actions">
        {step > 0 ? (
          <button className="button secondary" type="button"
            onClick={() => setStep((current) => current - 1)}>
            Back
          </button>
        ) : <span />}
        <button className="button primary" type="submit">
          {step < 2 ? "Continue" : "Preview candidate experience"}
        </button>
      </div>
    </form>
  );
}
