"use client";

/**
 * reasoning-store-hook.ts
 *
 * React hook for subscribing to the reasoning store.
 * Separated from reasoning-store.ts to keep React imports
 * out of modules that may be evaluated during SSR.
 */

import { useSyncExternalStore } from "react";
import {
  subscribe,
  getEntriesSnapshot,
  getActiveSnapshot,
  type ReasoningEntry,
} from "./reasoning-store";

/**
 * Subscribe to reasoning entries — re-renders when new entries arrive or
 * active state changes.
 */
export function useReasoningEntries(): {
  entries: ReasoningEntry[];
  isActive: boolean;
} {
  const entries = useSyncExternalStore(subscribe, getEntriesSnapshot, getEntriesSnapshot);
  const isActive = useSyncExternalStore(subscribe, getActiveSnapshot, getActiveSnapshot);
  return { entries, isActive };
}
