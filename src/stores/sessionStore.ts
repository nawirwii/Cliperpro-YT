import { create } from "zustand";
import type { Highlight, SessionData } from "@/hooks/highlights";

export type SessionOrigin = "create" | "library";

interface SessionState {
  session: SessionData | null;
  origin: SessionOrigin;
  selectedIndices: Set<number>;
  setSession: (session: SessionData, origin?: SessionOrigin) => void;
  clearSession: () => void;
  /** Mark highlight indices as processed (rendered) for the given session. */
  markProcessed: (sessionDir: string, indices: number[]) => void;
  /** v2.0.141: per-highlight intro topics, keyed by sessionDir then highlight
      index. In-memory only (same durability as markProcessed): survives page
      navigation inside the app, resets on app restart. The topic NEVER feeds
      the clip title or filename. */
  highlightTopics: Record<string, Record<number, string>>;
  setHighlightTopic: (sessionDir: string, index: number, topic: string) => void;
  /** v2.0.142: per-highlight intro/outro video paths, keyed by sessionDir
      then highlight index. In-memory only (same durability as
      highlightTopics): survives page navigation inside the app, resets on
      app restart. A null pick means "fall back to the global intro/outro
      from the Process Clips dialog" for that clip. */
  highlightIntros: Record<string, Record<number, string>>;
  highlightOutros: Record<string, Record<number, string>>;
  setHighlightIntro: (sessionDir: string, index: number, path: string | null) => void;
  setHighlightOutro: (sessionDir: string, index: number, path: string | null) => void;
  toggleSelected: (index: number) => void;
  selectAll: () => void;
  deselectAll: () => void;
  getSelectedHighlights: () => Highlight[];
}

export const useSessionStore = create<SessionState>((set, get) => ({
  session: null,
  origin: "create",
  selectedIndices: new Set(),

  highlightTopics: {},

  // v2.0.141: store an intro topic for one highlight. Guarded by sessionDir
  // so a stale topic is never applied to another session.
  setHighlightTopic: (sessionDir, index, topic) =>
    set((state) => ({
      highlightTopics: {
        ...state.highlightTopics,
        [sessionDir]: {
          ...(state.highlightTopics[sessionDir] ?? {}),
          [index]: topic,
        },
      },
    })),

  highlightIntros: {},
  highlightOutros: {},

  // v2.0.142: store an intro video path for one highlight. A null path
  // removes the pick (fall back to the global intro). Guarded by
  // sessionDir so a stale pick is never applied to another session.
  setHighlightIntro: (sessionDir, index, path) =>
    set((state) => {
      const perSession = { ...(state.highlightIntros[sessionDir] ?? {}) };
      if (path === null) delete perSession[index];
      else perSession[index] = path;
      return {
        highlightIntros: { ...state.highlightIntros, [sessionDir]: perSession },
      };
    }),

  // v2.0.142: same as setHighlightIntro, for the outro video path.
  setHighlightOutro: (sessionDir, index, path) =>
    set((state) => {
      const perSession = { ...(state.highlightOutros[sessionDir] ?? {}) };
      if (path === null) delete perSession[index];
      else perSession[index] = path;
      return {
        highlightOutros: { ...state.highlightOutros, [sessionDir]: perSession },
      };
    }),

  setSession: (session, origin = "create") =>
    set({
      session,
      origin,
      // v2.0.143: never pre-select an already-processed highlight. The
      // button count and the cards already hide processed highlights,
      // so starting from the unprocessed ones keeps the selection state
      // truthful (before this, all indices were pre-selected and a
      // processed highlight could never leave the set).
      selectedIndices: new Set(
        session.highlights
          .map((_, i) => i)
          .filter((i) => !(session.processed_highlights ?? []).includes(i)),
      ),
    }),

  clearSession: () => set({ session: null, selectedIndices: new Set() }),

  // v2.0.132: record rendered clips so the highlights page shows the
  // "Clip ready" footer (View + open folder button). Guarded by
  // sessionDir so a stale store session is never marked.
  markProcessed: (sessionDir, indices) =>
    set((state) => {
      const session = state.session;
      if (!session || session.session_dir !== sessionDir || indices.length === 0) return {};
      const next = new Set(session.processed_highlights ?? []);
      indices.forEach((i) => next.add(i));
      // v2.0.143: a processed highlight leaves the selection, so it can
      // never be sent to the backend again by any caller.
      const selected = new Set(state.selectedIndices);
      indices.forEach((i) => selected.delete(i));
      return {
        session: {
          ...session,
          processed_highlights: [...next].sort((a, b) => a - b),
        },
        selectedIndices: selected,
      };
    }),

  toggleSelected: (index) =>
    set((state) => {
      const next = new Set(state.selectedIndices);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return { selectedIndices: next };
    }),

  selectAll: () =>
    set((state) => ({
      // v2.0.143: select only highlights that still need processing, so
      // the set matches the "Process N clips" button count and the card
      // checkmarks (processed cards already render unchecked).
      selectedIndices: new Set(
        (state.session?.highlights.map((_, i) => i) ?? []).filter(
          (i) => !(state.session?.processed_highlights ?? []).includes(i),
        ),
      ),
    })),

  deselectAll: () => set({ selectedIndices: new Set() }),

  getSelectedHighlights: () => {
    const { session, selectedIndices } = get();
    if (!session) return [];
    // v2.0.143: the single source of truth for "processed" is
    // session.processed_highlights. A processed highlight is never
    // returned, even if its index is still in selectedIndices (before
    // this, the filter below was the only one, so a processed highlight
    // that could not be unchecked was still sent to the backend).
    const processed = new Set(session.processed_highlights ?? []);
    return session.highlights.filter((_, i) => selectedIndices.has(i) && !processed.has(i));
  },
}));
