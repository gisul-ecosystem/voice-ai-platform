/**
 * Shared sessionStorage draft for the admin wizard
 * (design → review → invite).
 *
 * getSnapshot must return a stable object reference when the stored JSON
 * is unchanged — otherwise useSyncExternalStore infinite-loops (React #185).
 */

export const ROLE_DRAFT_KEY = "ai-interview:role-draft";

export type RoleDraftState = {
  definitionId: string;
  title: string;
  role: string;
  seniority: string;
  durationMinutes: string;
  jobDescription: string;
  competencies: string;
  startsAt: string;
  draft?: Record<string, unknown>;
  published?: unknown;
};

export type RoleDraftBundle = {
  state?: RoleDraftState;
  error: string;
};

export const EMPTY_ROLE_DRAFT: RoleDraftBundle = { error: "" };
export const ROLE_DRAFT_LOAD_ERROR: RoleDraftBundle = {
  error: "The draft could not be loaded.",
};

let snapshotCache: { raw: string | null; value: RoleDraftBundle } | null =
  null;

/** Local `YYYY-MM-DDTHH:mm` for `<input type="datetime-local">`. */
export function toLocalDateTimeValue(date: Date): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function defaultStartsAtLocal(from: Date = new Date()): string {
  return toLocalDateTimeValue(new Date(from.getTime() + 10 * 60_000));
}

export function invalidateRoleDraftCache(): void {
  snapshotCache = null;
}

export function writeRoleDraft(state: RoleDraftState): void {
  sessionStorage.setItem(ROLE_DRAFT_KEY, JSON.stringify(state));
  invalidateRoleDraftCache();
}

export function getRoleDraftSnapshot(): RoleDraftBundle {
  try {
    const raw = sessionStorage.getItem(ROLE_DRAFT_KEY);
    if (snapshotCache && snapshotCache.raw === raw) {
      return snapshotCache.value;
    }
    const value: RoleDraftBundle = raw
      ? { state: JSON.parse(raw) as RoleDraftState, error: "" }
      : EMPTY_ROLE_DRAFT;
    snapshotCache = { raw, value };
    return value;
  } catch {
    return ROLE_DRAFT_LOAD_ERROR;
  }
}

/** Noop subscribe — sessionStorage has no change events we need for the wizard. */
export function subscribeRoleDraft(): () => void {
  return () => undefined;
}

export type SavedDefinitionSummary = {
  definition_id: string;
  title: string;
  role: string;
  seniority: string;
  duration_minutes: number;
  timezone: string;
  competencies: string[];
  job_description: string;
  published_at?: string | null;
  published_by?: string | null;
};

/** Hydrate wizard state from a Mongo-published definition so Invite can reuse it. */
export function roleDraftFromSavedDefinition(
  item: SavedDefinitionSummary,
  startsAt: string = defaultStartsAtLocal(),
): RoleDraftState {
  const definitionId = item.definition_id;
  return {
    definitionId,
    title: item.title || "Interview",
    role: item.role || item.title || "Role",
    seniority: item.seniority || "mid",
    durationMinutes: String(item.duration_minutes || 30),
    jobDescription: item.job_description || "",
    competencies: (item.competencies || []).join(", "),
    startsAt,
    draft: {
      title: item.title,
      reused_definition_id: definitionId,
    },
    published: {
      definition_id: definitionId,
      title: item.title,
      status: "published",
    },
  };
}
