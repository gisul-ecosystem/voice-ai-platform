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
