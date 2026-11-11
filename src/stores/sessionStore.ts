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

  setSession: (session, origin = "create") =>
    set({
      session,
      origin,
      selectedIndices: new Set(session.highlights.map((_, i) => i)),
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
      return {
        session: {
          ...session,
          processed_highlights: [...next].sort((a, b) => a - b),
        },
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
      selectedIndices: new Set(state.session?.highlights.map((_, i) => i) ?? []),
    })),

  deselectAll: () => set({ selectedIndices: new Set() }),

  getSelectedHighlights: () => {
    const { session, selectedIndices } = get();
    if (!session) return [];
    return session.highlights.filter((_, i) => selectedIndices.has(i));
  },
}));
