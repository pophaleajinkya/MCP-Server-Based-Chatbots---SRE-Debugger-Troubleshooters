/**
 * reasoning-store.ts
 *
 * Pure JavaScript store for reasoning/thinking entries — NO React imports.
 * Safe to import from any context (adapter, chat-helpers, SSR, client).
 *
 * The A2A adapter pushes entries here; React components subscribe via the
 * useReasoningEntries() hook in reasoning-store-hook.ts.
 */

// ─── Types ──────────────────────────────────────────────────────────────────

export interface ReasoningEntry {
  type: "thinking" | "reasoning";
  text: string;
  ts: number; // epoch ms
}

// ─── Store ──────────────────────────────────────────────────────────────────

export type Listener = () => void;

let _entries: ReasoningEntry[] = [];
let _isActive = false;
const _listeners = new Set<Listener>();

function notify() {
  for (const fn of _listeners) fn();
}

/** Push a new reasoning entry (called from the adapter). */
export function pushReasoning(entry: ReasoningEntry): void {
  _entries = [..._entries, entry]; // immutable update for React
  notify();
}

/** Mark reasoning as active/inactive (maps to isProcessing in the stream). */
export function setReasoningActive(active: boolean): void {
  _isActive = active;
  notify();
}

/** Clear all entries (call on new conversation / session switch). */
export function clearReasoning(): void {
  _entries = [];
  _isActive = false;
  notify();
}

/** Subscribe to store changes — used by the React hook. */
export function subscribe(cb: Listener) {
  _listeners.add(cb);
  return () => { _listeners.delete(cb); };
}

/** Snapshot accessors — used by useSyncExternalStore. */
export function getEntriesSnapshot(): ReasoningEntry[] {
  return _entries;
}

export function getActiveSnapshot(): boolean {
  return _isActive;
}
