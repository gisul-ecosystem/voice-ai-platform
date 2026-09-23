import { useState } from "react";
import { useRouter } from "next/navigation";

export const defaultStart = new Date(Date.now() + 10 * 60_000).toISOString().slice(0, 16);
export const DRAFT_KEY = "ai-interview:role-draft";

export type RoleDraft = {
  title: string;
  role: string;
  seniority: string;
  durationMinutes: string;
  jobDescription: string;
  competencies: string;
  definitionId: string;
  startsAt: string;
  difficulty: string;
  language: string;
  monitoringEnabled: boolean;
  recordingEnabled: boolean;
  draft?: Record<string, unknown>;
};

export function useDesignForm() {
  const router = useRouter();
  const [value, setValue] = useState<RoleDraft>({
    title: "", role: "", seniority: "",
    durationMinutes: "30", jobDescription: "", competencies: "",
    definitionId: "ai-engineer-junior-v1", startsAt: defaultStart,
    difficulty: "applied", language: "English",
    monitoringEnabled: true, recordingEnabled: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newCompetency, setNewCompetency] = useState("");
  const [ingestBusy, setIngestBusy] = useState(false);

  function setField<K extends keyof RoleDraft>(key: K, next: RoleDraft[K]) {
    setValue((current) => ({ ...current, [key]: next }));
  }

  function competencyList(): string[] {
    const raw = value.competencies.split(",").map((item) => item.trim()).filter(Boolean);
    return raw.filter((item, index, all) => all.findIndex(other => other.toLowerCase() === item.toLowerCase()) === index).slice(0, 8);
  }

  function setCompetencyList(items: string[]) {
    setField("competencies", items.join(", "));
  }

  function addCompetency() {
    const item = newCompetency.trim();
    if (!item || competencyList().some((current) => current.toLowerCase() === item.toLowerCase())) return;
    setCompetencyList([...competencyList(), item]);
    setNewCompetency("");
  }

  function itemTexts(items: unknown): string[] {
    if (!Array.isArray(items)) return [];
    return items.map((item) => {
      if (typeof item === "string") return item.trim();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (item && typeof item === "object" && "text" in item) return String((item as any).text || "").trim();
      return "";
    }).filter(Boolean);
  }

  async function ingestDocument(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setIngestBusy(true); setError("");
    try {
      const body = new FormData();
      body.set("kind", "jd");
      body.set("file", file, file.name);
      body.set("target_level", value.seniority);
      const response = await fetch("/api/brain/ingest", { method: "POST", body });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const payload = (await response.json().catch(() => ({}))) as any;
      if (!response.ok || typeof payload.text !== "string") throw new Error(payload.error || "Document could not be processed.");
      let newCompetencies = value.competencies;
      let newRole = value.role;
      if (payload.jobIntelligence && typeof payload.jobIntelligence === "object") {
        if (payload.jobIntelligence.role?.title && !value.role.trim()) newRole = payload.jobIntelligence.role.title;
        const suggested = [...itemTexts(payload.jobIntelligence.mandatory_requirements), ...itemTexts(payload.jobIntelligence.skills)]
          .filter((item, index, all) => all.findIndex((other) => other.toLowerCase() === item.toLowerCase()) === index);
        if (suggested.length) {
          const merged = [...value.competencies.split(",").map(c => c.trim()).filter(Boolean), ...suggested];
          newCompetencies = merged.filter((item, index, all) => all.findIndex(other => other.toLowerCase() === item.toLowerCase()) === index).slice(0, 8).join(", ");
        }
      }
      setValue(cur => ({ ...cur, jobDescription: payload.text, role: newRole, competencies: newCompetencies }));
    } catch (e) { setError(e instanceof Error ? e.message : "Document could not be processed."); }
    finally { setIngestBusy(false); }
  }

  async function ingestTextContent(text: string) {
    if (!text.trim()) return;
    setIngestBusy(true); setError("");
    try {
      const body = new FormData();
      body.set("kind", "jd");
      const blob = new Blob([text], { type: "text/plain" });
      body.set("file", blob, "pasted-jd.txt");
      body.set("target_level", value.seniority);
      const response = await fetch("/api/brain/ingest", { method: "POST", body });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const payload = (await response.json().catch(() => ({}))) as any;
      if (!response.ok || typeof payload.text !== "string") throw new Error(payload.error || "Document could not be processed.");
      let newCompetencies = value.competencies;
      let newRole = value.role;
      let newTitle = value.title;
      let newSeniority = value.seniority;
      if (payload.jobIntelligence && typeof payload.jobIntelligence === "object") {
        if (payload.jobIntelligence.role?.title) {
          newRole = payload.jobIntelligence.role.title;
          newTitle = `${payload.jobIntelligence.role.title} interview`;
        }
        if (payload.jobIntelligence.role?.target_level) {
          newSeniority = payload.jobIntelligence.role.target_level;
        }
        let suggested: string[] = [];
        if (Array.isArray(payload.jobIntelligence.core_competencies) && payload.jobIntelligence.core_competencies.length > 0) {
          suggested = payload.jobIntelligence.core_competencies as string[];
        } else {
          suggested = [...itemTexts(payload.jobIntelligence.mandatory_requirements), ...itemTexts(payload.jobIntelligence.skills)]
            .filter((item, index, all) => all.findIndex((other) => other.toLowerCase() === item.toLowerCase()) === index);
        }
        if (suggested.length) {
          const merged = [...value.competencies.split(",").map(c => c.trim()).filter(Boolean), ...suggested];
          newCompetencies = merged.filter((item, index, all) => all.findIndex(other => other.toLowerCase() === item.toLowerCase()) === index).slice(0, 8).join(", ");
        }
      }
      setValue(cur => ({ ...cur, jobDescription: payload.text, role: newRole, title: newTitle, seniority: newSeniority, competencies: newCompetencies }));
    } catch (e) { setError(e instanceof Error ? e.message : "Document could not be processed."); }
    finally { setIngestBusy(false); }
  }

  async function generate() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/admin/blueprint", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({
        action: "compile", title: value.title, seniority: value.seniority, durationMinutes: Number(value.durationMinutes),
        language: value.language, jobDescription: value.jobDescription,
        competencies: value.competencies.split(",").map((item) => item.trim()).filter(Boolean),
      }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(data.error || data.detail || "Alignment generation failed."));
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ ...value, draft: data }));
      router.push("/interviewer/admin/review");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Alignment generation failed."); }
    finally { setBusy(false); }
  }

  return {
    value,
    busy,
    error,
    newCompetency,
    ingestBusy,
    setField,
    setNewCompetency,
    competencyList,
    setCompetencyList,
    addCompetency,
    ingestDocument,
    ingestTextContent,
    generate,
  };
}
