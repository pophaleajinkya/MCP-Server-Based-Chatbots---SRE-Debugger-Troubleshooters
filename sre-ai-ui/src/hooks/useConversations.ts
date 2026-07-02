"use client";

import { useState, useCallback, useEffect } from "react";
import { v4 as uuidv4 } from "uuid";
import type { Conversation } from "@/types";
import { fetchConversations } from "@/lib/sessions-client";

const STORAGE_KEY = "adk_active_session_id";

export function useConversations(userId = "", enabled = true, initialSessionId?: string) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>(() => {
    // Priority: shared link (?session=) → last localStorage session → new UUID
    if (initialSessionId) return initialSessionId;
    if (typeof window !== "undefined") {
      return localStorage.getItem(STORAGE_KEY) || uuidv4();
    }
    return uuidv4();
  });
  const [loading, setLoading] = useState(true);

  // Tracks whether the user arrived via a shared link and has not yet taken
  // any explicit navigation action (select / new chat). Once the user acts,
  // we drop out of "shared link" mode regardless of the session list.
  const [isSharedSession, setIsSharedSession] = useState(() => !!initialSessionId);

  // Session is read-only when:
  //  1. User arrived via a shared link and the session belongs to someone else, OR
  //  2. The active session is a shared session with permission="read"
  const activeConversation = conversations.find((c) => c.session_id === activeSessionId);
  const isReadOnly =
    !loading && (
      // Shared link case — session not in own list
      (isSharedSession && !activeConversation) ||
      // Explicitly shared session with read-only permission
      (activeConversation?.shared_by !== undefined && activeConversation.permission !== "write")
    );
    
  const isAlertSession = activeConversation?.tags?.some(t => t.toLowerCase().includes("alert")) ?? false;

  // Keep URL and localStorage in sync whenever the active session changes.
  // Uses history.replaceState so the address bar is always shareable without
  // adding noise to the browser history stack.
  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(STORAGE_KEY, activeSessionId);
    const url = new URL(window.location.href);
    url.searchParams.set("session", activeSessionId);
    window.history.replaceState(null, "", url.toString());
  }, [activeSessionId]);

  const refresh = useCallback(async () => {
    if (!enabled || !userId) return;
    setLoading(true);
    try {
      const data = await fetchConversations(userId);
      setConversations(data);
    } finally {
      setLoading(false);
    }
  }, [userId, enabled]);

  // Only fetch once auth is ready (enabled = true)
  useEffect(() => {
    if (!enabled) return;
    refresh();
  }, [refresh, enabled]);

  const createNewConversation = useCallback(() => {
    setIsSharedSession(false);
    const newId = uuidv4();
    setActiveSessionId(newId);
    return newId;
  }, []);

  const selectConversation = useCallback((sessionId: string) => {
    setIsSharedSession(false);
    setActiveSessionId(sessionId);
  }, []);

  // Update or insert a conversation title after the first message
  const updateConversationTitle = useCallback((sessionId: string, title: string) => {
    setConversations((prev) => {
      const exists = prev.find((c) => c.session_id === sessionId);
      if (exists) {
        return prev.map((c) =>
          c.session_id === sessionId ? { ...c, title } : c
        );
      }
      // Add new conversation at the top
      const newConv: Conversation = {
        session_id: sessionId,
        title,
        last_update_time: Date.now() / 1000,
        user_id: userId,
      };
      return [newConv, ...prev];
    });
  }, [userId]);

  return {
    conversations,
    activeSessionId,
    loading,
    isReadOnly,
    isAlertSession,
    refresh,
    createNewConversation,
    selectConversation,
    updateConversationTitle,
  };
}
